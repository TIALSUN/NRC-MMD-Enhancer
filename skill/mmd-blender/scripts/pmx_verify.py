#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pmx_verify.py — 独立 PMX 兼容性验证器（不依赖 Blender）。

输入 PMX（可选同目录 report.json），输出结构化检查结果：pass / warn / fail。
用法：
  python pmx_verify.py <pmx> [--report <report.json>] [--json-out out.json] [--quiet]
  python pmx_verify.py --batch <root> [--json-out out.json] [--csv-out out.csv] [--limit N]

检查覆盖：文件头/版本/字节完整性、数量、材质（贴图存在性+大小写、texture_index、
diffuse alpha、双面/描边 flags、无贴图材质）、骨骼（标准骨齐全性、IK 配置、重复骨名、
NaN、权重索引）、表情（数量 ≥100、索引有效性、关键表情覆盖）、物理（刚体/关节索引、
NaN）、网格（NaN/Inf、退化三角、UV、法线、权重和）、纹理（Tex/ 存在且被引用、
report.textures_unbound 对照）、显示枠索引、report 元数据一致性。
"""
import argparse
import csv
import hashlib
import json
import math
import os
import struct
import sys
import time
from collections import Counter, OrderedDict
from pathlib import Path

FAIL, WARN, PASS, INFO = "fail", "warn", "pass", "info"
SEV_ORDER = {PASS: 0, INFO: 1, WARN: 2, FAIL: 3}

# ---------------------------------------------------------------- 标准表
STANDARD_BONES_REQUIRED = [
    "センター", "上半身", "首", "頭",
    "左腕", "右腕", "左ひじ", "右ひじ", "左手首", "右手首",
    "左足", "右足", "左ひざ", "右ひざ", "左足首", "右足首",
    "左つま先", "右つま先",
]
STANDARD_BONES_RECOMMENDED = [
    "下半身", "上半身2", "左肩", "右肩", "左足ＩＫ", "右足ＩＫ",
    "左つま先ＩＫ", "右つま先ＩＫ", "左目", "右目", "両目",
    "左足D", "右足D", "左ひざD", "右ひざD", "左足首D", "右足首D",
    "左足先EX", "右足先EX", "左腕捩", "右腕捩",
]
CORE_MORPHS = [
    "まばたき", "あ", "い", "う", "え", "お",
    "笑い", "ウィンク", "じと目", "真面目", "怒り", "困る", "にっこり", "びっくり",
]
MORPH_COUNT_EXPECTED = 100  # 任务约定：表情 morph 数量预期 ≥100

MATERIAL_FLAG_NAMES = [
    (0x01, "両面描画"), (0x02, "地面影"), (0x04, "セルフシャドウマップ"),
    (0x08, "セルフシャドウ"), (0x10, "輪郭線"), (0x20, "頂点カラー"),
    (0x40, "点描画"), (0x80, "線描画"),
]
MATERIAL_TYPES = {0: "BDEF1", 1: "BDEF2", 2: "BDEF4", 3: "SDEF", 4: "QDEF"}
MORPH_TYPE_NAMES = {
    0: "group", 1: "vertex", 2: "bone", 3: "uv", 4: "uv1", 5: "uv2",
    6: "uv3", 7: "uv4", 8: "material", 9: "flip", 10: "impulse",
}


class PmxError(Exception):
    def __init__(self, message, offset=None):
        self.message = message
        self.offset = offset
        super().__init__(message)


class Reader:
    """PMX 小端二进制读取，带越界检查。"""

    __slots__ = ("d", "o", "n")

    def __init__(self, data):
        self.d = data
        self.o = 0
        self.n = len(data)

    def need(self, k):
        if self.o + k > self.n:
            raise PmxError("读越界：offset=%d 需要 %d 字节，文件仅 %d" % (self.o, k, self.n), self.o)

    def u8(self):
        self.need(1)
        v = self.d[self.o]
        self.o += 1
        return v

    def i8(self):
        self.need(1)
        v = struct.unpack_from("<b", self.d, self.o)[0]
        self.o += 1
        return v

    def u16(self):
        self.need(2)
        v = struct.unpack_from("<H", self.d, self.o)[0]
        self.o += 2
        return v

    def i32(self):
        self.need(4)
        v = struct.unpack_from("<i", self.d, self.o)[0]
        self.o += 4
        return v

    def f32(self):
        self.need(4)
        v = struct.unpack_from("<f", self.d, self.o)[0]
        self.o += 4
        return v

    def fl(self, k):
        if k == 0:
            return ()
        self.need(4 * k)
        v = struct.unpack_from("<%df" % k, self.d, self.o)
        self.o += 4 * k
        return v

    def take(self, k):
        self.need(k)
        b = self.d[self.o:self.o + k]
        self.o += k
        return b

    def text(self, enc):
        n = self.i32()
        if n < 0 or n > self.n - self.o:
            raise PmxError("文本长度非法：%d @%d" % (n, self.o), self.o)
        raw = self.take(n)
        if enc == 0:
            try:
                return raw.decode("utf-16-le")
            except UnicodeDecodeError:
                return raw.decode("utf-16-le", "replace")
        if enc == 1:
            try:
                return raw.decode("utf-8")
            except UnicodeDecodeError:
                return raw.decode("utf-8", "replace")
        raise PmxError("未知编码 %d" % enc, self.o)

    def idx(self, size, signed=True):
        if size == 1:
            return self.i8() if signed else self.u8()
        if size == 2:
            self.need(2)
            v = struct.unpack_from("<h" if signed else "<H", self.d, self.o)[0]
            self.o += 2
            return v
        if size == 4:
            return self.i32() if signed else struct.unpack("<I", self.take(4))[0]
        raise PmxError("非法索引宽度 %d" % size, self.o)


def _count(r, label, min_record=1):
    v = r.i32()
    if v < 0:
        raise PmxError("%s 数量为负：%d" % (label, v), r.o)
    if v > 8_000_000:
        raise PmxError("%s 数量异常：%d" % (label, v), r.o)
    if v * min_record > r.n - r.o:
        raise PmxError("%s 数量 %d 超出剩余字节（需要 >=%d，剩余 %d）"
                       % (label, v, v * min_record, r.n - r.o), r.o)
    return v


def parse_pmx(path):
    """解析 PMX 文件，返回 dict。语义错误抛 PmxError（带 offset）。"""
    data = Path(path).read_bytes()
    r = Reader(data)
    info = {"file_size": len(data), "version": None, "encoding": None,
            "globals": None, "add_uv": 0, "index_sizes": {}, "parse_ok": False,
            "parse_error": None, "parsed_bytes": 0}
    try:
        magic = r.take(4)
        if magic != b"PMX ":
            raise PmxError("magic 不是 'PMX '，实际 %r" % (magic,), 0)
        version = r.f32()
        info["version"] = round(version, 4)
        if not math.isfinite(version) or not (1.5 <= version <= 2.5):
            raise PmxError("版本号异常：%r" % (version,), 4)
        gc = r.u8()
        info["globals_count"] = gc
        if gc != 8:
            raise PmxError("globals 数量应为 8，实际 %d" % gc, r.o)
        g = list(r.take(gc))
        enc = g[0]
        if enc not in (0, 1):
            raise PmxError("编码标志非法：%d" % enc, r.o - gc)
        add_uv = g[1]
        if add_uv not in (0, 1, 2, 3, 4):
            raise PmxError("追加 UV 数量非法：%d" % add_uv, r.o - gc + 1)
        vi, ti, mi, bi, moi, rbi = g[2:8]
        sizes = {"vertex": vi, "texture": ti, "material": mi, "bone": bi,
                 "morph": moi, "rigidbody": rbi}
        for k, v in sizes.items():
            if v not in (1, 2, 4):
                raise PmxError("索引宽度非法 %s=%d" % (k, v), r.o)
        info.update({"encoding": enc, "globals": g, "add_uv": add_uv,
                     "index_sizes": sizes})
        info["name"] = r.text(enc)
        info["name_en"] = r.text(enc)
        info["comment"] = r.text(enc)
        info["comment_en"] = r.text(enc)

        # 顶点
        nv = _count(r, "顶点", 32)
        vpos, vnrm, vuv, vwt = [], [], [], []
        wtype_counter = Counter()
        for _ in range(nv):
            vpos.append(r.fl(3))
            vnrm.append(r.fl(3))
            vuv.append(r.fl(2))
            if add_uv:
                r.fl(4 * add_uv)
            wt = r.u8()
            wtype_counter[wt] += 1
            if wt == 0:
                w = ((r.idx(bi), 1.0),)
            elif wt == 1:  # BDEF2: bone0 bone1 weight
                a = r.idx(bi); b2 = r.idx(bi); wv = r.f32()
                w = ((a, wv), (b2, 1.0 - wv))
            elif wt == 2:  # BDEF4
                ids = [r.idx(bi) for _ in range(4)]
                ws = r.fl(4)
                w = tuple(zip(ids, ws))
            elif wt == 3:  # SDEF: bone0 bone1 weight C R0 R1
                a = r.idx(bi); b2 = r.idx(bi); wv = r.f32()
                r.fl(9)  # C, R0, R1
                w = ((a, wv), (b2, 1.0 - wv))
            elif wt == 4:  # QDEF
                ids = [r.idx(bi) for _ in range(4)]
                ws = r.fl(4)
                w = tuple(zip(ids, ws))
            else:
                raise PmxError("未知顶点权重类型 %d" % wt, r.o)
            r.f32()  # edge scale
            vwt.append(w)
        info["vertex_weight_types"] = dict(wtype_counter)

        # 面
        nf = _count(r, "面索引", vi)
        if nf % 3:
            info["faces_not_multiple_of_3"] = nf % 3
        faces = [r.idx(vi, False) for _ in range(nf)]

        # 贴图
        nt = _count(r, "贴图", 4)
        textures = [r.text(enc) for _ in range(nt)]

        # 材质
        nm = _count(r, "材质", 80)
        materials = []
        for _ in range(nm):
            m = {}
            m["name"] = r.text(enc)
            m["name_en"] = r.text(enc)
            m["diffuse"] = r.fl(4)
            m["specular"] = r.fl(3)
            m["specularity"] = r.f32()
            m["ambient"] = r.fl(3)
            m["flags"] = r.u8()
            m["edge_color"] = r.fl(4)
            m["edge_size"] = r.f32()
            m["texture"] = r.idx(ti)
            m["env_texture"] = r.idx(ti)
            m["blend_mode"] = r.u8()
            toon_ref = r.u8()
            if toon_ref == 0:
                m["toon_texture"] = r.idx(ti)
                m["toon_value"] = None
            else:
                m["toon_texture"] = -1
                m["toon_value"] = r.u8()
            m["memo"] = r.text(enc)
            m["faces"] = r.i32()
            materials.append(m)

        # 骨骼
        nb = _count(r, "骨骼", 40)
        bones = []
        for _ in range(nb):
            b = {}
            b["name"] = r.text(enc)
            b["name_en"] = r.text(enc)
            b["pos"] = r.fl(3)
            b["parent"] = r.idx(bi)
            b["layer"] = r.i32()
            f = r.u16()
            b["flags"] = f
            if f & 0x0001:
                b["tail_bone"] = r.idx(bi)
                b["tail_pos"] = None
            else:
                b["tail_bone"] = None
                b["tail_pos"] = r.fl(3)
            if f & 0x0100 or f & 0x0200:
                b["grant_parent"] = r.idx(bi)
                b["grant_weight"] = r.f32()
            else:
                b["grant_parent"] = None
                b["grant_weight"] = None
            b["fixed_axis"] = r.fl(3) if f & 0x0400 else None
            b["local_axis"] = r.fl(6) if f & 0x0800 else None
            b["external_parent"] = r.i32() if f & 0x2000 else None
            b["ik"] = None
            if f & 0x0020:
                ik = {"target": r.idx(bi), "loop": r.i32(), "limit": r.f32(), "links": []}
                n = r.i32()
                if n < 0 or n > 64:
                    raise PmxError("IK 链长度非法：%d" % n, r.o)
                for _ in range(n):
                    lb = r.idx(bi)
                    has = r.u8()
                    lo = hi = None
                    if has:
                        lo = r.fl(3)
                        hi = r.fl(3)
                    ik["links"].append({"bone": lb, "limit": bool(has), "min": lo, "max": hi})
                b["ik"] = ik
            bones.append(b)

        # 表情
        nmo = _count(r, "表情", 8)
        morphs = []
        for _ in range(nmo):
            mo = {"name": r.text(enc), "name_en": r.text(enc),
                  "panel": r.u8(), "type": r.u8(), "offsets": []}
            cnt = r.i32()
            if cnt < 0 or cnt > 2_000_000:
                raise PmxError("表情偏移数量非法：%d" % cnt, r.o)
            t = mo["type"]
            for _ in range(cnt):
                if t == 0:      # group
                    mo["offsets"].append((r.idx(moi), r.f32()))
                elif t == 1:    # vertex
                    mo["offsets"].append((r.idx(vi, False), r.fl(3)))
                elif t == 2:    # bone
                    mo["offsets"].append((r.idx(bi), r.fl(3), r.fl(4)))
                elif t in (3, 4, 5, 6, 7):  # uv / uv1..4
                    mo["offsets"].append((r.idx(vi, False), r.fl(4)))
                elif t == 8:    # material
                    mi_ = r.idx(mi)
                    mo["offsets"].append((mi_, r.u8(), r.fl(4), r.fl(3), r.f32(),
                                          r.fl(3), r.fl(4), r.f32(), r.fl(4), r.fl(4), r.fl(4)))
                elif t == 9:    # flip (2.1)
                    mo["offsets"].append((r.idx(moi), r.f32()))
                elif t == 10:   # impulse (2.1)
                    mo["offsets"].append((r.idx(rbi), r.u8(), r.fl(3), r.fl(3)))
                else:
                    raise PmxError("未知表情类型 %d" % t, r.o)
            morphs.append(mo)

        # 显示枠
        nd = _count(r, "显示枠", 20)
        frames = []
        for _ in range(nd):
            fr = {"name": r.text(enc), "name_en": r.text(enc), "special": r.u8(), "entries": []}
            cnt = r.i32()
            if cnt < 0 or cnt > 100000:
                raise PmxError("显示枠条目数量非法：%d" % cnt, r.o)
            for _ in range(cnt):
                et = r.u8()
                if et == 0:
                    fr["entries"].append((0, r.idx(bi)))
                elif et == 1:
                    fr["entries"].append((1, r.idx(moi)))
                else:
                    raise PmxError("未知显示枠条目类型 %d" % et, r.o)
            frames.append(fr)

        # 刚体
        nrb = _count(r, "刚体", 60)
        rigids = []
        for _ in range(nrb):
            rb = {
                "name": r.text(enc), "name_en": r.text(enc), "bone": r.idx(bi),
                "group": r.u8(), "mask": r.u16(), "shape": r.u8(),
                "size": r.fl(3), "pos": r.fl(3), "rot": r.fl(3),
                "mass": r.f32(), "move_atten": r.f32(), "rot_damp": r.f32(),
                "repulsion": r.f32(), "friction": r.f32(), "mode": r.u8(),
            }
            rigids.append(rb)

        # 关节
        nj = _count(r, "关节", 120)
        joints = []
        for _ in range(nj):
            j = {
                "name": r.text(enc), "name_en": r.text(enc), "type": r.u8(),
                "a": r.idx(rbi), "b": r.idx(rbi),
                "pos": r.fl(3), "rot": r.fl(3),
                "pos_min": r.fl(3), "pos_max": r.fl(3),
                "rot_min": r.fl(3), "rot_max": r.fl(3),
                "spring_pos": r.fl(3), "spring_rot": r.fl(3),
            }
            joints.append(j)

        # 软体（PMX 2.1）
        soft_bodies = []
        if version >= 2.1:
            nsb = _count(r, "软体", 4)
            for _ in range(nsb):
                sb = {"name": r.text(enc), "name_en": r.text(enc)}
                sb["shape"] = r.u8()
                sb["material"] = r.idx(mi)
                sb["group"] = r.u8()
                sb["mask"] = r.u16()
                sb["flags"] = r.u8()
                sb["b_link_distance"] = r.f32()
                sb["cluster_count"] = r.i32()
                sb["total_mass"] = r.f32()
                sb["collision_margin"] = r.f32()
                sb["aero_model"] = r.i32()
                sb["config"] = r.fl(14)
                na = r.i32()
                if na < 0 or na > 4_000_000:
                    raise PmxError("软体锚点数量非法：%d" % na, r.o)
                sb["anchors"] = [r.idx(vi, False) for _ in range(na)]
                npin = r.i32()
                if npin < 0 or npin > 4_000_000:
                    raise PmxError("软体固定点数量非法：%d" % npin, r.o)
                sb["pins"] = [r.idx(vi, False) for _ in range(npin)]
                soft_bodies.append(sb)

        info["parsed_bytes"] = r.o
        info["remaining_bytes"] = r.n - r.o
        info["parse_ok"] = True
    except PmxError as e:
        info["parse_error"] = {"message": e.message, "offset": e.offset,
                               "parsed_bytes": r.o, "file_size": r.n}
        info["parsed_bytes"] = r.o
        info["remaining_bytes"] = r.n - r.o
        return {"info": info,
                "verts": {"pos": [], "normal": [], "uv": [], "weights": []},
                "faces": [], "textures": [], "materials": [], "bones": [],
                "morphs": [], "frames": [], "rigids": [], "joints": [],
                "soft_bodies": []}

    return {"info": info, "verts": {"pos": vpos, "normal": vnrm, "uv": vuv, "weights": vwt},
            "faces": faces, "textures": textures, "materials": materials,
            "bones": bones, "morphs": morphs, "frames": frames,
            "rigids": rigids, "joints": joints, "soft_bodies": soft_bodies}


# ---------------------------------------------------------------- 检查工具
class Checker:
    def __init__(self):
        self.checks = []

    def add(self, cid, category, title, severity, detail="", samples=None, metrics=None):
        c = {"id": cid, "category": category, "title": title,
             "severity": severity, "detail": detail}
        if samples:
            c["samples"] = list(samples)[:12]
        if metrics:
            c["metrics"] = metrics
        self.checks.append(c)
        return c

    def worst(self):
        sev = PASS
        for c in self.checks:
            if SEV_ORDER[c["severity"]] > SEV_ORDER[sev]:
                sev = c["severity"]
        return sev


def _finite(vals):
    for v in vals:
        if not isinstance(v, (int, float)):
            return False
        if not math.isfinite(v):
            return False
    return True


def _fmt(vals):
    return "(" + ", ".join(("%.4g" % v) if isinstance(v, float) else str(v) for v in vals) + ")"


class TextureResolver:
    def __init__(self, pmx_dir):
        self.root = Path(pmx_dir)
        self._listings = {}

    def _listing(self, d):
        d = str(d)
        if d not in self._listings:
            try:
                self._listings[d] = {e.name.casefold(): e.name for e in Path(d).iterdir()}
            except OSError:
                self._listings[d] = {}
        return self._listings[d]

    def resolve(self, tex):
        """返回 dict: raw/norm/absolute/exists/actual/case_mismatch/escape/missing_part"""
        raw = tex
        norm = tex.replace("\\", "/")
        res = {"raw": raw, "norm": norm, "absolute": False, "exists": False,
               "actual": None, "case_mismatch": False, "escape": False}
        if not norm:
            return res
        if len(norm) > 1 and norm[1] == ":":  # Windows 绝对路径
            res["absolute"] = True
            p = Path(norm)
            res["exists"] = p.is_file()
            res["actual"] = str(p)
            return res
        parts = [p for p in norm.split("/") if p not in ("", ".")]
        if ".." in parts:
            res["escape"] = True
            p = (self.root / Path(*parts))
            res["exists"] = p.is_file()
            res["actual"] = str(p)
            return res
        cur = self.root
        actual_parts = []
        for part in parts:
            listing = self._listing(cur)
            exact = cur / part
            if exact.exists():
                actual_parts.append(part)
            else:
                cf = listing.get(part.casefold())
                if cf is not None:
                    res["case_mismatch"] = True
                    actual_parts.append(cf)
                else:
                    res["missing_part"] = part
                    break
            cur = cur / actual_parts[-1]
        else:
            res["exists"] = cur.is_file()
            res["actual"] = str(cur)
            if not res["exists"]:
                res["missing_part"] = parts[-1]
        return res


def verify(pmx_path, report_path=None, strict_report=True):
    """验证单个 PMX，返回结构化结果 dict。"""
    t0 = time.time()
    pmx_path = Path(pmx_path).resolve()
    ck = Checker()
    data = parse_pmx(pmx_path)
    info = data["info"]
    verts, faces = data["verts"], data["faces"]
    textures, materials = data["textures"], data["materials"]
    bones, morphs = data["bones"], data["morphs"]
    rigids, joints, frames = data["rigids"], data["joints"], data["frames"]
    softb = data["soft_bodies"]

    sha = hashlib.sha256()
    with open(pmx_path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            sha.update(chunk)
    sha256 = sha.hexdigest()

    counts = {
        "vertices": len(verts["pos"]), "faces": len(faces), "triangles": len(faces) // 3,
        "textures": len(textures), "materials": len(materials), "bones": len(bones),
        "morphs": len(morphs), "display_frames": len(frames),
        "rigidbodies": len(rigids), "joints": len(joints), "soft_bodies": len(softb),
    }

    # ---------- 1. 文件头/版本/完整性
    if not info["parse_ok"]:
        err = info["parse_error"]
        ck.add("parse_error", "file", "PMX 解析失败", FAIL,
               "解析在 offset=%s 中断（文件 %d 字节）：%s"
               % (err.get("offset"), info["file_size"], err.get("message")),
               metrics={"offset": err.get("offset"), "file_size": info["file_size"]})
    else:
        ck.add("header_magic", "file", "文件头 magic 'PMX '", PASS)
        v = info["version"]
        if v in (2.0, 2.1):
            ck.add("header_version", "file", "版本号 %s（MMD/MikuMikuDance 支持 2.0，2.1 需 PMXEditor）"
                   % v, PASS if v == 2.0 else WARN)
        else:
            ck.add("header_version", "file", "版本号异常：%s" % v, FAIL)
        ck.add("header_encoding", "file", "文本编码 %s" % ("UTF-16LE" if info["encoding"] == 0 else "UTF-8"),
               PASS)
        bad = {k: v2 for k, v2 in info["index_sizes"].items() if v2 not in (1, 2, 4)}
        ck.add("header_index_sizes", "file", "索引宽度配置", PASS if not bad else FAIL,
               detail=json.dumps(info["index_sizes"], ensure_ascii=False))
        name_ok = bool(info["name"].strip())
        ck.add("header_name", "file", "模型名非空（%r）" % info["name"], PASS if name_ok else FAIL)
        rem = info["remaining_bytes"]
        if rem == 0:
            ck.add("file_integrity", "file", "字节完整性：解析消耗 %d = 文件大小（无多余字节）"
                   % info["parsed_bytes"], PASS)
        else:
            ck.add("file_integrity", "file", "字节完整性：解析后剩余 %d 字节（可能存在多余/未知区块）" % rem,
                   WARN if rem > 0 else FAIL, metrics={"remaining": rem})

    # ---------- 2. 数量基本合法性
    empty = [k for k in ("vertices", "faces", "materials", "bones") if counts[k] == 0]
    ck.add("counts_basic", "count", "基本数量", FAIL if empty else PASS,
           detail="顶点 %(vertices)d / 三角 %(triangles)d / 材质 %(materials)d / 骨 %(bones)d / 表情 %(morphs)d / 刚体 %(rigidbodies)d / 关节 %(joints)d"
           % counts,
           metrics=counts)
    if counts["morphs"] == 0:
        ck.add("counts_morphs", "count", "模型不含任何表情 morph（MMD 无法做表情）", WARN,
               detail="表情 0 个")
    if info.get("faces_not_multiple_of_3"):
        ck.add("counts_faces_mod3", "count", "面索引数不是 3 的倍数", FAIL,
               detail="余数 %d" % info["faces_not_multiple_of_3"])

    # ---------- 3. report 对照
    report = None
    rep_checks = []
    if report_path is None:
        cand = pmx_path.parent / (pmx_path.stem + ".report.json")
        if cand.is_file():
            report_path = cand
    if report_path is not None:
        try:
            report = json.loads(Path(report_path).read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            rep_checks.append(("report_parse", FAIL, "report 读取失败：%s" % e))
    if report is not None:
        rp = report
        def rep(field):
            return rp.get(field)
        # 元数据
        probs = []
        if rep("pmx_sha256") and rep("pmx_sha256") != sha256:
            probs.append("sha256 不一致")
        if isinstance(rep("pmx_bytes"), int) and rep("pmx_bytes") != info["file_size"]:
            probs.append("pmx_bytes %s != 文件 %d" % (rep("pmx_bytes"), info["file_size"]))
        rep_checks.append(("report_meta", FAIL if probs else PASS,
                           "report 元数据一致性" + ("：" + "；".join(probs) if probs else "")))
        # 计数
        pairs = [("vertices", "vertices", "顶点"), ("triangles", "triangles", "三角"),
                 ("materials", "materials", "材质")]
        mism = []
        for rf, cf, label in pairs:
            rv = rep(rf)
            cv = counts[cf]
            if isinstance(rv, int) and rv != cv:
                delta = abs(cv - rv) / max(1, rv)
                mism.append((label, rv, cv, delta))
        if not mism:
            rep_checks.append(("report_counts", PASS, "report 计数与 PMX 一致"))
        else:
            severe = [m for m in mism if m[3] > 0.05]
            detail = "；".join("%s report=%d pmx=%d（Δ%.2f%%）" % (m[0], m[1], m[2], 100 * m[3])
                              for m in mism)
            if not severe:
                detail += "（PMX 按 UV/法线接缝拆分顶点，少量差异属正常）"
            rep_checks.append(("report_counts", FAIL if severe else INFO, detail))
        # 骨骼数：report 记录的是骨架重命名阶段的数量，PMX 里还会追加 locator/发丝/衣物等骨，
        # 因此不一致只作 warn 提示（用于核对导出流程是否丢了骨）。
        rb = rep("bones_after_rename")
        if isinstance(rb, int) and rb != counts["bones"]:
            rep_checks.append(("report_bones", INFO,
                               "report.bones_after_rename=%d 与 PMX 骨数 %d 不同（PMX 追加了 %+d 个 locator/发丝/衣物骨，属导出流程预期）"
                               % (rb, counts["bones"], counts["bones"] - rb)))
        # 表达式数量
        rex = rep("expressions")
        if isinstance(rex, int):
            if rex > counts["morphs"]:
                rep_checks.append(("report_expressions", FAIL,
                                   "report.expressions=%d > PMX morph 数 %d" % (rex, counts["morphs"])))
            else:
                rep_checks.append(("report_expressions", PASS,
                                   "report.expressions=%d <= PMX morph 数 %d（其余为修复/元_ 条目）"
                                   % (rex, counts["morphs"])))
        # 标准骨 / IK 骨名
        std = rep("standard_bones")
        if isinstance(std, list):
            names = {b["name"] for b in bones}
            miss = [n for n in std if n not in names]
            rep_checks.append(("report_standard_bones", WARN if miss else PASS,
                               "report.standard_bones 缺失 %d 项%s"
                               % (len(miss), ("：" + ", ".join(miss[:8])) if miss else "")))
        ikb = rep("ik_bones")
        if isinstance(ikb, list):
            names = {b["name"]: b for b in bones}
            miss = [n for n in ikb if n not in names]
            noflag = [n for n in ikb if n in names and not (names[n]["flags"] & 0x0020)]
            bad = miss + noflag
            rep_checks.append(("report_ik_bones", WARN if bad else PASS,
                               "report.ik_bones 缺失/未标 IK %d 项%s"
                               % (len(bad), ("：" + ", ".join(bad[:8])) if bad else "")))
        # textures_unbound 对照
        unb = rep("textures_unbound")
        if isinstance(unb, list):
            matnames = {m["name"] for m in materials}
            phantom = [u for u in unb if isinstance(u, str) and u not in matnames]
            no_tex = {m["name"] for m in materials if m["texture"] < 0}
            unflagged = sorted(set(unb) & no_tex) if unb else []
            unknown = [u for u in unb if u not in no_tex]
            sev = PASS
            detail = "report.textures_unbound=%d 项" % len(unb)
            if phantom:
                sev = WARN
                detail += "；PMX 中不存在的材质 %d 个：%s" % (len(phantom), ", ".join(phantom[:6]))
            if unknown:
                sev = WARN
                detail += "；清单内材质在 PMX 中仍有贴图：%s" % ", ".join(unknown[:6])
            rep_checks.append(("report_textures_unbound", sev, detail))
        for cid, sev, detail in rep_checks:
            ck.add(cid, "report", "report 对照", sev, detail)
    else:
        if pmx_path.name and not strict_report:
            ck.add("report_missing", "report", "无 report.json（跳过对照）", INFO)
        else:
            ck.add("report_missing", "report", "未找到/无法读取 report.json（跳过对照）", INFO)

    # ---------- 4. 材质
    if materials:
        pmx_dir = pmx_path.parent
        tr = TextureResolver(pmx_dir)
        ntex = len(textures)
        bad_tex_idx, bad_toon, bad_env = [], [], []
        no_tex, low_alpha, out_alpha, double_sided, outlined = [], [], [], [], []
        tex_missing, tex_case, tex_abs, tex_bad_ext = [], [], [], []
        tex_cache = {}
        face_sum = 0
        empty_mats = []
        dup_names = []
        seen = Counter()
        png_checked = set()
        for i, m in enumerate(materials):
            nm_ = m["name"]
            seen[nm_] += 1
            if m["texture"] >= ntex or m["texture"] < -1:
                bad_tex_idx.append((nm_, m["texture"]))
            if m["toon_texture"] >= ntex or m["toon_texture"] < -1:
                bad_toon.append((nm_, m["toon_texture"]))
            if m["env_texture"] >= ntex or m["env_texture"] < -1:
                bad_env.append((nm_, m["env_texture"]))
            if m["texture"] < 0:
                no_tex.append(nm_)
            else:
                tex = textures[m["texture"]]
                key = tex.replace("\\", "/")
                if key not in tex_cache:
                    tex_cache[key] = tr.resolve(tex)
                r = tex_cache[key]
                ext = os.path.splitext(r["norm"])[1].lower()
                if r["absolute"]:
                    tex_abs.append((nm_, tex))
                if ext not in (".png", ".jpg", ".jpeg", ".bmp", ".tga", ".dds", ""):
                    tex_bad_ext.append((nm_, tex))
                if r["case_mismatch"]:
                    tex_case.append((nm_, tex))
                if not r["exists"]:
                    tex_missing.append((nm_, tex))
            a = m["diffuse"][3]
            if not math.isfinite(a) or not (0.0 <= a <= 1.0):
                out_alpha.append((nm_, a))
            elif a < 0.05:
                low_alpha.append((nm_, a))
            if m["flags"] & 0x01:
                double_sided.append(nm_)
            if m["flags"] & 0x10:
                outlined.append(nm_)
            face_sum += m["faces"]
            if m["faces"] == 0:
                empty_mats.append(nm_)
        dup_names = [n for n, c in seen.items() if c > 1]

        ck.add("mat_texture_index", "material", "texture_index 有效性",
               FAIL if bad_tex_idx else PASS,
               detail="" if not bad_tex_idx else "越界材质 %d 个" % len(bad_tex_idx),
               samples=["%s -> %d" % x for x in bad_tex_idx])
        ck.add("mat_toon_env_index", "material", "toon/env texture_index 有效性",
               FAIL if (bad_toon or bad_env) else PASS,
               detail="toon 越界 %d；env 越界 %d" % (len(bad_toon), len(bad_env)),
               samples=["toon:%s -> %d" % x for x in bad_toon] + ["env:%s -> %d" % x for x in bad_env])
        ck.add("mat_texture_missing", "material", "贴图文件存在性",
               FAIL if tex_missing else PASS,
               detail="缺失 %d / %d 个引用" % (len(tex_missing), len(tex_cache)),
               samples=["%s -> %s" % x for x in tex_missing])
        ck.add("mat_texture_case", "material", "贴图路径大小写一致性",
               WARN if tex_case else PASS,
               detail="大小写不匹配 %d 个（Windows 可读，Linux/打包环境可能失败）" % len(tex_case),
               samples=["%s -> %s" % x for x in tex_case])
        ck.add("mat_texture_absolute", "material", "贴图路径为绝对路径",
               WARN if tex_abs else PASS,
               detail="绝对路径 %d 个（不可迁移，重命名/移动模型后会失效）" % len(tex_abs),
               samples=["%s -> %s" % x for x in tex_abs])
        if tex_bad_ext:
            ck.add("mat_texture_ext", "material", "贴图扩展名非 MMD 常用格式",
                   WARN, detail="%d 个" % len(tex_bad_ext),
                   samples=["%s -> %s" % x for x in tex_bad_ext])
        ck.add("mat_no_texture", "material", "无贴图材质",
               WARN if no_tex else PASS,
               detail="%d 个材质无贴图" % len(no_tex), samples=no_tex)
        ck.add("mat_diffuse_alpha", "material", "diffuse alpha 范围",
               FAIL if out_alpha else PASS,
               detail="越界 %d 个；alpha<0.05（近全透明）%d 个" % (len(out_alpha), len(low_alpha)),
               samples=["%s alpha=%.3f" % x for x in out_alpha + low_alpha])
        ck.add("mat_flags", "material", "材质 flags（双面/描边等）",
               PASS, detail="双面 %d；描边 %d；比例 双面 %.1f%% 描边 %.1f%%"
               % (len(double_sided), len(outlined),
                  100.0 * len(double_sided) / len(materials), 100.0 * len(outlined) / len(materials)),
               metrics={"double_sided": len(double_sided), "outline": len(outlined)})
        total_faces = counts["triangles"] * 3
        ck.add("mat_face_sum", "material", "材质面数之和 = 面索引数",
               FAIL if face_sum != total_faces else PASS,
               detail="材质合计 %d / 面索引 %d" % (face_sum, total_faces))
        ck.add("mat_empty", "material", "空材质（0 面）", WARN if empty_mats else PASS,
               detail="%d 个" % len(empty_mats), samples=empty_mats)
        ck.add("mat_duplicate_names", "material", "材质重名", WARN if dup_names else PASS,
               detail="%d 组" % len(dup_names), samples=dup_names)

        # ---------- 纹理目录：Tex/ 存在且被引用
        tex_dir = pmx_dir / "Tex"
        referenced = set()
        for m in materials:
            if 0 <= m["texture"] < ntex:
                referenced.add(textures[m["texture"]].replace("\\", "/").casefold())
        if tex_dir.is_dir():
            files = [p for p in tex_dir.rglob("*") if p.is_file()]
            rel_all = []
            unreferenced = []
            for p in files:
                rel = p.relative_to(pmx_dir).as_posix()
                rel_all.append(rel)
                if rel.casefold() not in referenced:
                    unreferenced.append(rel)
            ck.add("tex_dir_exists", "texture", "Tex/ 目录存在（%d 个文件）" % len(files), PASS)
            ck.add("tex_unreferenced", "texture", "Tex/ 下未被任何材质引用的文件",
                   WARN if unreferenced else PASS,
                   detail="未引用 %d / %d 个" % (len(unreferenced), len(files)),
                   samples=unreferenced)
            # 采样检查贴图文件可解码、尺寸>0
            try:
                from PIL import Image
                bad_img = []
                zero_files = []
                for p in files[:400]:
                    if p.stat().st_size == 0:
                        zero_files.append(str(p.relative_to(pmx_dir)))
                        continue
                    try:
                        with Image.open(p) as im:
                            if im.size[0] == 0 or im.size[1] == 0:
                                bad_img.append(str(p.relative_to(pmx_dir)))
                    except Exception:  # noqa: BLE001
                        bad_img.append(str(p.relative_to(pmx_dir)))
                ck.add("tex_decodable", "texture", "贴图文件可解码/尺寸有效",
                       FAIL if bad_img else PASS,
                       detail="损坏/零尺寸 %d 个；空文件 %d 个" % (len(bad_img), len(zero_files)),
                       samples=bad_img + zero_files)
            except Exception:  # noqa: BLE001
                ck.add("tex_decodable", "texture", "贴图可解码检查（Pillow 不可用，跳过）", INFO)
        else:
            any_referenced = bool(referenced)
            ck.add("tex_dir_exists", "texture", "Tex/ 目录存在",
                   WARN if any_referenced else INFO,
                   detail="PMX 引用的贴图 %d 个，但 %s 不存在" % (len(referenced), tex_dir))
            # 引用贴图若散落在 PMX 目录其他位置也算存在（前面已检查）

    # ---------- 5. 骨骼
    nb = len(bones)
    if bones:
        names = [b["name"] for b in bones]
        nameset = set(names)
        miss_req = [n for n in STANDARD_BONES_REQUIRED if n not in nameset]
        miss_rec = [n for n in STANDARD_BONES_RECOMMENDED if n not in nameset]
        ck.add("bone_standard_required", "bone", "标准骨齐全性（必需 %d）" % len(STANDARD_BONES_REQUIRED),
               FAIL if miss_req else PASS,
               detail="缺失 %d：%s" % (len(miss_req), ", ".join(miss_req[:12])))
        ck.add("bone_standard_recommended", "bone", "标准骨齐全性（推荐 %d）" % len(STANDARD_BONES_RECOMMENDED),
               WARN if miss_rec else PASS,
               detail="缺失 %d：%s" % (len(miss_rec), ", ".join(miss_rec[:12])))
        dup = [n for n, c in Counter(names).items() if c > 1]
        ck.add("bone_duplicate_names", "bone", "重复骨名", FAIL if dup else PASS,
               detail="%d 组：%s" % (len(dup), ", ".join(dup[:10])))
        nan_bones = [b["name"] for b in bones
                     if not _finite(b["pos"]) or (b["tail_pos"] and not _finite(b["tail_pos"]))]
        ck.add("bone_nan", "bone", "骨骼坐标 NaN/Inf", FAIL if nan_bones else PASS,
               detail="%d 个：%s" % (len(nan_bones), ", ".join(nan_bones[:10])))
        bad_parent = [(b["name"], b["parent"]) for b in bones
                      if b["parent"] < -1 or b["parent"] >= nb]
        ck.add("bone_parent_index", "bone", "父骨索引有效性", FAIL if bad_parent else PASS,
               detail="%d 个越界" % len(bad_parent), samples=["%s -> %s" % x for x in bad_parent])
        bad_tail = [(b["name"], b["tail_bone"]) for b in bones
                    if b["tail_bone"] is not None and not (0 <= b["tail_bone"] < nb)]
        ck.add("bone_tail_index", "bone", "tail 骨索引有效性", FAIL if bad_tail else PASS,
               detail="%d 个越界" % len(bad_tail), samples=["%s -> %s" % x for x in bad_tail])
        # IK 配置
        ik_problems = []
        ik_count = 0
        for b in bones:
            ik = b["ik"]
            if not ik:
                continue
            ik_count += 1
            tgt = ik["target"]
            if not (0 <= tgt < nb):
                ik_problems.append("%s: target 索引越界 %d" % (b["name"], tgt))
                continue
            tname = bones[tgt]["name"]
            if ik["loop"] <= 0 or ik["loop"] > 255:
                ik_problems.append("%s: loop=%d 非法" % (b["name"], ik["loop"]))
            if not _finite((ik["limit"],)):
                ik_problems.append("%s: limit 非有限" % b["name"])
            if not ik["links"]:
                ik_problems.append("%s: 无 IK 链" % b["name"])
            for lk in ik["links"]:
                if not (0 <= lk["bone"] < nb):
                    ik_problems.append("%s: 链骨索引越界 %d" % (b["name"], lk["bone"]))
                    break
                if lk["limit"] and (not _finite(lk["min"] or ()) or not _finite(lk["max"] or ())):
                    ik_problems.append("%s: 链骨角度限制非有限（%s）" % (b["name"], bones[lk["bone"]]["name"]))
                    break
            if b["name"].endswith("足ＩＫ") and "つま先" not in b["name"]:
                if not tname.endswith("足首"):
                    ik_problems.append("%s: target=%s（期望 *足首）" % (b["name"], tname))
                chain = [bones[lk["bone"]]["name"] for lk in ik["links"]
                         if 0 <= lk["bone"] < nb]
                if not any(c.endswith("ひざ") for c in chain):
                    ik_problems.append("%s: 链中无 *ひざ（%s）" % (b["name"], ",".join(chain)))
            if b["name"].endswith("つま先ＩＫ"):
                if not tname.endswith("つま先"):
                    ik_problems.append("%s: target=%s（期望 *つま先）" % (b["name"], tname))
        n_ik_expected = sum(1 for n in names if n.endswith("足ＩＫ") or n.endswith("つま先ＩＫ"))
        ck.add("bone_ik", "bone", "IK 配置（IK 骨 %d 个）" % ik_count,
               FAIL if ik_problems else PASS,
               detail="问题 %d 项%s" % (len(ik_problems), ("" if not ik_problems else "：" + "；".join(ik_problems[:6]))),
               metrics={"ik_bones": ik_count, "ik_name_candidates": n_ik_expected})
        if n_ik_expected and ik_count < n_ik_expected:
            ck.add("bone_ik_missing", "bone", "存在名为 *ＩＫ 但未标 IK 的骨",
                   WARN, detail="%d 个未标 IK" % (n_ik_expected - ik_count))

    # ---------- 6. 顶点权重 / 网格
    if verts["pos"]:
        vp, vn, vu, vw = verts["pos"], verts["normal"], verts["uv"], verts["weights"]
        nan_pos = [i for i, p in enumerate(vp) if not _finite(p)]
        ck.add("mesh_nan_vertices", "mesh", "顶点坐标 NaN/Inf", FAIL if nan_pos else PASS,
               detail="%d 个（示例索引 %s）" % (len(nan_pos), nan_pos[:10]))
        nan_nrm = [i for i, n in enumerate(vn) if not _finite(n)]
        ck.add("mesh_nan_normals", "mesh", "法线 NaN/Inf", FAIL if nan_nrm else PASS,
               detail="%d 个" % len(nan_nrm))
        zero_nrm = [i for i, n in enumerate(vn)
                    if _finite(n) and (abs(n[0]) + abs(n[1]) + abs(n[2])) < 1e-6]
        bad_len = [i for i, n in enumerate(vn)
                   if _finite(n) and abs(math.sqrt(n[0] * n[0] + n[1] * n[1] + n[2] * n[2]) - 1.0) > 0.1]
        ck.add("mesh_normals", "mesh", "法线零长度/非单位化",
               WARN if (zero_nrm or bad_len) else PASS,
               detail="零长度 %d；非单位 %d" % (len(zero_nrm), len(bad_len)),
               samples=[str(i) for i in (zero_nrm + bad_len)[:10]])
        nan_uv = [i for i, u in enumerate(vu) if not _finite(u)]
        far_uv = [i for i, u in enumerate(vu)
                  if _finite(u) and (abs(u[0]) > 64 or abs(u[1]) > 64)]
        oob_uv = [i for i, u in enumerate(vu)
                  if _finite(u) and not (0.0 <= u[0] <= 1.0 and 0.0 <= u[1] <= 1.0)]
        uv_ratio = 100.0 * len(oob_uv) / max(1, len(vu))
        ck.add("mesh_uv", "mesh", "UV NaN/越界",
               FAIL if nan_uv else (WARN if (far_uv or uv_ratio > 2.0) else (INFO if oob_uv else PASS)),
               detail="NaN %d；超出 [0,1] %d（%d/%d，%.2f%%，MMD 会按贴图重复采样）；|uv|>64 %d"
               % (len(nan_uv), len(oob_uv), len(oob_uv), len(vu), uv_ratio, len(far_uv)),
               metrics={"oob": len(oob_uv), "far": len(far_uv), "nan": len(nan_uv),
                        "oob_pct": round(uv_ratio, 3)})
        # 面索引
        bad_idx = [i for i, f in enumerate(faces) if not (0 <= f < len(vp))]
        ck.add("mesh_face_index", "mesh", "面顶点索引有效性", FAIL if bad_idx else PASS,
               detail="越界 %d / %d" % (len(bad_idx), len(faces)))
        # 退化三角
        degen = 0
        dup_tri = 0
        seen_tri = set()
        for t in range(len(faces) // 3):
            a, b, c = faces[3 * t], faces[3 * t + 1], faces[3 * t + 2]
            if a == b or b == c or a == c:
                degen += 1
                continue
            ax, ay, az = vp[a]
            bx, by, bz = vp[b]
            cx, cy, cz = vp[c]
            ux, uy, uz = bx - ax, by - ay, bz - az
            wx, wy, wz = cx - ax, cy - ay, cz - az
            nx = uy * wz - uz * wy
            ny = uz * wx - ux * wz
            nz = ux * wy - uy * wx
            if nx * nx + ny * ny + nz * nz < 1e-12:
                degen += 1
            key = tuple(sorted((a, b, c)))
            if key in seen_tri:
                dup_tri += 1
            else:
                seen_tri.add(key)
        ntri = max(1, len(faces) // 3)
        ratio = 100.0 * degen / ntri
        ck.add("mesh_degenerate", "mesh", "退化三角（零面积/重复顶点）",
               FAIL if ratio > 5 else WARN if degen else PASS,
               detail="%d / %d（%.2f%%）；重复三角形 %d" % (degen, ntri, ratio, dup_tri),
               metrics={"degenerate": degen, "dup_tri": dup_tri})
        # 权重
        bad_bone_w = []
        bad_sum = []
        neg_w = []
        for i, w in enumerate(vw):
            s = 0.0
            for bidx, wt in w:
                if bidx < 0 or bidx >= nb:
                    if len(bad_bone_w) < 20:
                        bad_bone_w.append((i, bidx))
                if not math.isfinite(wt):
                    neg_w.append(i)
                elif wt < -1e-6:
                    neg_w.append(i)
                s += wt if math.isfinite(wt) else 0.0
            if abs(s - 1.0) > 0.02:
                bad_sum.append((i, round(s, 4)))
        ck.add("mesh_weight_bone_index", "mesh", "顶点权重骨索引有效性",
               FAIL if bad_bone_w else PASS,
               detail="越界 %d%s" % (len(bad_bone_w), ("（示例 %s）" % bad_bone_w[:8]) if bad_bone_w else ""))
        ck.add("mesh_weight_sum", "mesh", "顶点权重和 ≈ 1",
               WARN if bad_sum else PASS,
               detail="偏差>0.02 的顶点 %d 个%s" % (len(bad_sum), ("（示例 %s）" % bad_sum[:8]) if bad_sum else ""))
        ck.add("mesh_weight_negative", "mesh", "顶点权重负值/非有限",
               FAIL if neg_w else PASS, detail="%d 个顶点" % len(neg_w))

    # ---------- 7. 表情
    nm = len(morphs)
    morph_names = {m["name"] for m in morphs}
    ck.add("morph_count", "morph", "表情 morph 数量（预期 ≥%d）" % MORPH_COUNT_EXPECTED,
           PASS if nm >= MORPH_COUNT_EXPECTED else WARN,
           detail="实际 %d（含修复/元_ 条目）" % nm, metrics={"morphs": nm})
    miss_core = [n for n in CORE_MORPHS if n not in morph_names]
    ck.add("morph_core_coverage", "morph", "关键表情覆盖（%d 项）" % len(CORE_MORPHS),
           WARN if len(miss_core) > 2 else (INFO if miss_core else PASS),
           detail="缺失 %d：%s" % (len(miss_core), ", ".join(miss_core)))
    bad_morph_idx = []
    type_counter = Counter()
    for mi_, mo in enumerate(morphs):
        t = mo["type"]
        type_counter[MORPH_TYPE_NAMES.get(t, "type%d" % t)] += 1
        for off in mo["offsets"]:
            idx = off[0]
            if t == 0:
                ok = 0 <= idx < nm and idx != mi_
            elif t in (1, 3, 4, 5, 6, 7):
                ok = 0 <= idx < len(verts["pos"])
            elif t == 2:
                ok = 0 <= idx < len(bones)
            elif t == 8:
                ok = 0 <= idx < len(materials)
            elif t == 9:
                ok = 0 <= idx < nm
            elif t == 10:
                ok = 0 <= idx < len(rigids)
            else:
                ok = True
            if not ok:
                bad_morph_idx.append((mo["name"], t, idx))
    ck.add("morph_index", "morph", "morph 偏移索引有效性", FAIL if bad_morph_idx else PASS,
           detail="越界 %d 处" % len(bad_morph_idx),
           samples=["%s(type=%s) -> %s" % x for x in bad_morph_idx[:10]],
           metrics={"types": dict(type_counter)})
    # morph 位移 NaN
    nan_morph = []
    for mo in morphs:
        t = mo["type"]
        for off in mo["offsets"]:
            payload = []
            if t == 1:
                payload = list(off[1])
            elif t == 2:
                payload = list(off[1]) + list(off[2])
            elif t in (3, 4, 5, 6, 7):
                payload = list(off[1])
            elif t == 8:
                payload = list(off[2]) + list(off[3]) + [off[4]] + list(off[5]) + list(off[6]) + [off[7]]
            if payload and not _finite(payload):
                nan_morph.append((mo["name"], t))
                break
    ck.add("morph_nan", "morph", "morph 位移 NaN/Inf", FAIL if nan_morph else PASS,
           detail="%d 个 morph" % len(nan_morph), samples=["%s(type=%s)" % x for x in nan_morph[:10]])

    # ---------- 8. 物理
    nrb = len(rigids)
    if rigids:
        bad_rb_bone = [(r["name"], r["bone"]) for r in rigids
                       if r["bone"] < -1 or r["bone"] >= len(bones)]
        ck.add("phys_rigid_bone", "physics", "刚体骨索引有效性", FAIL if bad_rb_bone else PASS,
               detail="越界 %d" % len(bad_rb_bone), samples=["%s -> %s" % x for x in bad_rb_bone[:10]])
        bad_rb_shape = [(r["name"], r["shape"]) for r in rigids if r["shape"] not in (0, 1, 2)]
        ck.add("phys_rigid_shape", "physics", "刚体形状类型", FAIL if bad_rb_shape else PASS,
               detail="非法 %d" % len(bad_rb_shape), samples=["%s -> %s" % x for x in bad_rb_shape])
        nan_rb = []
        for r in rigids:
            if not (_finite(r["size"]) and _finite(r["pos"]) and _finite(r["rot"])
                    and _finite((r["mass"], r["move_atten"], r["rot_damp"], r["repulsion"], r["friction"]))):
                nan_rb.append(r["name"])
        ck.add("phys_rigid_nan", "physics", "刚体参数 NaN/Inf", FAIL if nan_rb else PASS,
               detail="%d 个" % len(nan_rb), samples=nan_rb[:10])
        grp_bad = [(r["name"], r["group"]) for r in rigids if not (0 <= r["group"] < 16)]
        ck.add("phys_rigid_group", "physics", "刚体分组 0-15", FAIL if grp_bad else PASS,
               detail="越界 %d" % len(grp_bad))
        dynamic_bodies = [r for r in rigids if r["mode"] != 0]
        modes = Counter(r["mode"] for r in rigids)
        if dynamic_bodies and not joints:
            ck.add("phys_rigid_dynamic_joints", "physics",
                   "存在动态刚体（mode≠0）但没有关节约束", WARN,
                   detail="动态刚体 %d 个、关节 0 个（MMD 中会自由下落/抖动）"
                   % len(dynamic_bodies),
                   metrics={"modes": dict(modes)})
        else:
            ck.add("phys_rigid_dynamic_joints", "physics",
                   "动态刚体与关节约束匹配", PASS,
                   detail="刚体模式分布 %s；关节 %d 个" % (dict(modes), len(joints)),
                   metrics={"modes": dict(modes), "joints": len(joints)})
    else:
        ck.add("phys_rigid", "physics", "无刚体（模型不含物理）", INFO)
    if joints:
        bad_j = [(j["name"], j["a"], j["b"]) for j in joints
                 if not (0 <= j["a"] < nrb) or not (0 <= j["b"] < nrb)]
        ck.add("phys_joint_ref", "physics", "关节刚体引用有效性", FAIL if bad_j else PASS,
               detail="越界 %d / %d" % (len(bad_j), len(joints)),
               samples=["%s -> (%s,%s)" % x for x in bad_j[:10]])
        bad_jt = [(j["name"], j["type"]) for j in joints if not (0 <= j["type"] <= 6)]
        ck.add("phys_joint_type", "physics", "关节类型", FAIL if bad_jt else PASS,
               detail="非法 %d" % len(bad_jt))
        nan_j = []
        for j in joints:
            vals = list(j["pos"]) + list(j["rot"]) + list(j["pos_min"]) + list(j["pos_max"]) \
                + list(j["rot_min"]) + list(j["rot_max"]) + list(j["spring_pos"]) + list(j["spring_rot"])
            if not _finite(vals):
                nan_j.append(j["name"])
        ck.add("phys_joint_nan", "physics", "关节参数 NaN/Inf", FAIL if nan_j else PASS,
               detail="%d 个" % len(nan_j), samples=nan_j[:10])

    # ---------- 9. 显示枠
    if frames:
        bad_fr = []
        for fr in frames:
            for et, idx in fr["entries"]:
                if et == 0 and not (0 <= idx < len(bones)):
                    bad_fr.append((fr["name"], "bone", idx))
                if et == 1 and not (0 <= idx < len(morphs)):
                    bad_fr.append((fr["name"], "morph", idx))
        ck.add("display_frame_index", "display", "显示枠条目索引有效性", FAIL if bad_fr else PASS,
               detail="越界 %d" % len(bad_fr), samples=["%s %s -> %s" % x for x in bad_fr[:10]])
        ck.add("display_frame_count", "display", "显示枠数量", PASS, detail="%d 个" % len(frames))
    if softb:
        ck.add("softbody", "physics", "PMX 2.1 软体", WARN,
               detail="含 %d 个软体（MMD 本体不支持 2.1 软体）" % len(softb))

    # ---------- 汇总
    summary = {
        "checks": len(ck.checks),
        "pass": sum(1 for c in ck.checks if c["severity"] == PASS),
        "info": sum(1 for c in ck.checks if c["severity"] == INFO),
        "warn": sum(1 for c in ck.checks if c["severity"] == WARN),
        "fail": sum(1 for c in ck.checks if c["severity"] == FAIL),
    }
    summary["verdict"] = FAIL if summary["fail"] else (WARN if summary["warn"] else PASS)

    result = {
        "pmx": str(pmx_path),
        "pmx_name": pmx_path.name,
        "report": str(report_path) if report_path else None,
        "file": {"bytes": info["file_size"], "sha256": sha256},
        "header": {k: info.get(k) for k in ("version", "encoding", "globals",
                                            "add_uv", "index_sizes", "name",
                                            "name_en", "parsed_bytes", "remaining_bytes",
                                            "vertex_weight_types")},
        "counts": counts,
        "checks": ck.checks,
        "summary": summary,
        "elapsed_ms": int((time.time() - t0) * 1000),
    }
    return result


# ---------------------------------------------------------------- 批量
def find_pmx_files(root):
    root = Path(root)
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for fn in filenames:
            if fn.lower().endswith(".pmx"):
                out.append(Path(dirpath) / fn)
    return sorted(out)


def find_report_for(pmx_path):
    p = Path(pmx_path)
    cand = p.parent / (p.stem + ".report.json")
    if cand.is_file():
        return cand
    for cand in sorted(p.parent.glob("*.report.json")):
        try:
            d = json.loads(cand.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        out = d.get("out")
        if isinstance(out, str) and Path(out).name == p.name:
            return cand
    return None


def _row(res):
    codes_fail = [c["id"] for c in res["checks"] if c["severity"] == FAIL]
    codes_warn = [c["id"] for c in res["checks"] if c["severity"] == WARN]
    c = res["counts"]
    return OrderedDict([
        ("pmx", res["pmx_name"]),
        ("path", res["pmx"]),
        ("bytes", res["file"]["bytes"]),
        ("version", res["header"].get("version")),
        ("vertices", c["vertices"]), ("triangles", c["triangles"]),
        ("materials", c["materials"]), ("bones", c["bones"]),
        ("morphs", c["morphs"]), ("rigidbodies", c["rigidbodies"]),
        ("joints", c["joints"]),
        ("verdict", res["summary"]["verdict"]),
        ("fails", res["summary"]["fail"]), ("warns", res["summary"]["warn"]),
        ("fail_checks", "|".join(codes_fail)),
        ("warn_checks", "|".join(codes_warn)),
    ])


def main(argv=None):
    ap = argparse.ArgumentParser(description="独立 PMX 兼容性验证器（不依赖 Blender）")
    ap.add_argument("pmx", nargs="?", help="单个 PMX 路径")
    ap.add_argument("--report", help="report.json 路径（缺省自动查找同目录同名 .report.json）")
    ap.add_argument("--batch", metavar="ROOT", help="批量验证目录下所有 PMX")
    ap.add_argument("--json-out", metavar="PATH", help="结果 JSON 输出路径")
    ap.add_argument("--csv-out", metavar="PATH", help="汇总 CSV 输出路径")
    ap.add_argument("--limit", type=int, default=0, help="批量模式最多验证 N 个")
    ap.add_argument("--quiet", action="store_true", help="只输出汇总")
    args = ap.parse_args(argv)

    results = []
    if args.batch:
        files = find_pmx_files(args.batch)
        if args.limit:
            files = files[: args.limit]
        if not files:
            print("未找到 PMX 文件：%s" % args.batch, file=sys.stderr)
            return 2
        print("批量验证 %d 个 PMX ..." % len(files), file=sys.stderr)
        for i, p in enumerate(files, 1):
            rep = find_report_for(p)
            try:
                res = verify(p, rep)
            except Exception as e:  # noqa: BLE001
                res = {"pmx": str(p), "pmx_name": p.name, "report": str(rep) if rep else None,
                       "file": {"bytes": p.stat().st_size if p.exists() else 0, "sha256": None},
                       "header": {}, "counts": {}, "checks": [{
                           "id": "internal_error", "category": "internal", "title": "验证器异常",
                           "severity": FAIL, "detail": "%s: %s" % (type(e).__name__, e)}],
                       "summary": {"checks": 1, "pass": 0, "info": 0, "warn": 0, "fail": 1,
                                   "verdict": FAIL}, "elapsed_ms": 0}
            results.append(res)
            s = res["summary"]
            print("[%d/%d] %-60s %-4s fail=%d warn=%d" % (i, len(files), p.name[:60],
                                                          s["verdict"].upper(), s["fail"], s["warn"]),
                  file=sys.stderr)
    elif args.pmx:
        res = verify(args.pmx, args.report)
        results.append(res)
        if not args.quiet:
            print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        ap.error("需要 <pmx> 或 --batch <root>")

    if args.batch and not args.quiet:
        print("\n%-58s %-4s %-5s %-5s %s" % ("pmx", "verdict", "fails", "warns", "fail_checks"))
        for res in results:
            r = _row(res) if res.get("counts") else None
            if r is None:
                print("%-58s %-4s" % (res["pmx_name"][:58], res["summary"]["verdict"]))
                continue
            print("%-58s %-4s %-5d %-5d %s" % (r["pmx"][:58], r["verdict"], r["fails"], r["warns"],
                                              r["fail_checks"][:80]))
        agg = Counter(res["summary"]["verdict"] for res in results)
        print("\n合计：%d 个，pass=%d warn=%d fail=%d" %
              (len(results), agg.get(PASS, 0), agg.get(WARN, 0), agg.get(FAIL, 0)))

    if args.batch and args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json_out).write_text(json.dumps(results, ensure_ascii=False, indent=2),
                                       encoding="utf-8")
        print("写出 %s" % args.json_out, file=sys.stderr)
    elif args.json_out and results:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json_out).write_text(json.dumps(results[0], ensure_ascii=False, indent=2),
                                       encoding="utf-8")
    if args.batch and args.csv_out:
        Path(args.csv_out).parent.mkdir(parents=True, exist_ok=True)
        rows = [_row(res) for res in results if res.get("counts")]
        with open(args.csv_out, "w", encoding="utf-8-sig", newline="") as fh:
            if rows:
                w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
                w.writeheader()
                for r in rows:
                    w.writerow(r)
        print("写出 %s" % args.csv_out, file=sys.stderr)
    return 0 if all(r["summary"]["verdict"] != FAIL for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
