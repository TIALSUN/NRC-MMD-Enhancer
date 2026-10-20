"""Native spring-bone coverage and a conservative PMX approximation, without Blender.

Source settings are resolved through uniform/item/bone inheritance. Cooked values
in inactive override fields are deliberately ignored. PMX uses a different solver;
wind, gravity overrides and runtime collider binding are reported, not emulated.
"""
import math

REVISION = 'native-clothing-v2-20261020'

# The game solver keeps these coat-tail chains close to the animated body with
# runtime collider/state data that PMX cannot reproduce from the scalar spring
# settings alone.  Keep their bones and skin weights, but do not create a
# misleading automatic rigid-body approximation until that behavior is mapped.
PHYSICS_BLOCKED_PREFIXES = ('Bone_M_WeiBa',)

def compile_character(raw):
    groups=[]
    for export in raw['exports']:
        if not export['name'].startswith('Default__'):
            continue
        for name,node in export['data'].get('Properties',{}).items():
            if not name.startswith('AnimGraphNode_MFSpringBoneGroup') or not isinstance(node,dict):
                continue
            for index,item in enumerate(node.get('Items',[])):
                settings=(node.get('UniformInputSpringConfigs',{}) if node.get('bUseUniformInputSpringConfigs') else item.get('inputSpringConfigs',{}))
                bones={}
                for bone in item.get('SpringBoneConfigs',[]):
                    effective=settings if bone.get('bUseInputConfigs') and item.get('bUseInputSpringConfigs') else bone.get('SpringConfigs',{})
                    # Only active scalar fields are used for the PMX approximation.
                    bones[bone['Bone']['BoneName']]={k:effective[k] for k in ('StiffnessForce','DragForce','SolveRate','bEnableGravity','EnableAllColider','RotationConstrainType') if k in effective}
                if bones:
                    groups.append({'source':raw['path'],'node':name,'index':index,'bones':bones,
                                   'runtime_colliders':bool(node.get('UniformAllColliders',{}).get('bRuntimeBinding'))})
    return {'groups':groups}

def validate_weighted_bones(parents, weighted):
    missing=sorted(name for name,w in weighted.items() if w>1e-4 and name not in parents)
    if missing:
        raise ValueError('Weighted bones missing from merged armature: '+', '.join(missing))
    return sorted(name for name,w in weighted.items() if w>1e-4)

def build_native_plan(parents, weighted, character):
    """Select configured clothing bones and their real ancestors, once per bone.

    Short-hair policy stays in the existing converter; no hair bones are claimed
    here. A branch is cut at its actual parent, never joined to an unrelated root.
    """
    validate_weighted_bones(parents,weighted)
    configs={};sources={};runtime_colliders=False
    for group in character.get('groups',[]):
        for name,settings in group['bones'].items():
            if name.startswith('Bone_M_TouFa'):
                continue
            if name not in configs:
                configs[name]=settings
                sources[name]={k:group[k] for k in ('source','node','index')}
        runtime_colliders |= group.get('runtime_colliders',False)
    blocked_weighted={name for name in configs
                      if weighted.get(name,0)>1e-4 and name.startswith(PHYSICS_BLOCKED_PREFIXES)}
    active=set()
    for name in sorted(configs):
        if name in blocked_weighted or name not in parents or weighted.get(name,0)<=1e-4:
            continue
        path=set();bone=name
        while bone in configs and bone in parents:
            if bone in path:raise ValueError('Cyclic native clothing bone hierarchy: '+bone)
            path.add(bone);bone=parents[bone]
        active.update(path)
    selected=[];claimed=set();skipped=[]
    for anchor in sorted({parents[b] for b in active if parents[b] not in active},key=str):
        if anchor is None:
            skipped.extend(sorted(b for b in active if parents[b] is None));continue
        branch=set()
        def walk(name,path):
            branch.add(name)
            kids=sorted(b for b in active if parents[b]==name)
            if not kids:return [path+[name]]
            return [p for child in kids for p in walk(child,path+[name])]
        chains=[p for b in sorted(active) if parents[b]==anchor for p in walk(b,[])]
        if not chains:continue
        selected.append({'label':'原生衣料_'+str(len(selected)+1),'anchor':anchor,'chains':chains,
                         'group':2,'collision_groups':{0},'mass':[1.5,1.2],
                         'rot':[.5,.25,.5],'damping':[.4,.5],'size':.55,
                         'native_settings':{b:configs[b] for b in branch},
                         'native_source':sources[chains[0][0]],
                         'native_sources':{b:sources[b] for b in branch},
                         'runtime_colliders':runtime_colliders})
        claimed.update(branch)
    return selected,{'configured_weighted_bones':sorted(b for b in claimed if weighted.get(b,0)>1e-4),
                     'physics_blocked_weighted_bones':sorted(blocked_weighted),
                     'configured_unweighted_bones_skipped':sorted(set(configs)-claimed-blocked_weighted),
                     'unanchored_bones_skipped':sorted(set(skipped))}


def pmx_spring_parameters(settings,mass,default_damping):
    """Heuristic conversion, not a claim of unit equivalence between solvers."""
    stiffness=float(settings.get('StiffnessForce',0))
    drag=float(settings.get('DragForce',default_damping))
    rate=float(settings.get('SolveRate',60))
    if not all(math.isfinite(v) for v in (stiffness,drag,rate)):
        raise ValueError('Non-finite native spring parameter')
    return {'angular_spring':max(0,min(10,stiffness*max(1,min(rate,120))*mass)),
            'damping':max(0,min(.95,drag))}
