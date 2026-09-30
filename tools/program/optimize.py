"""Shape-generic optimizations; no workload names or physics equations."""
from collections import defaultdict

ELEMENTWISE = frozenset(('add','add_any','sub','mul','div','neg','abs','sqrt',
    'acos','atan2','sin','cos','min','max','lt','le','gt','ge','eq','ne','select_n',
    'sign','convert_element_type','integer_pow','and','or','xor','not'))


def compose_indices(plan):
    """Compose static reorders without changing floating-point evaluation."""
    producers={};count=0
    for node in plan.nodes:
        for child in node.params.get('regions',[]):
            count+=compose_indices(child)
        if node.op=='index':
            previous=producers.get(node.inputs[0])
            if previous is not None and previous.op=='index':
                node.params['map']=[previous.params['map'][i] for i in node.params['map']]
                node.inputs=list(previous.inputs);count+=1
        producers[node.output]=node
    plan.dce()
    return count


def elementwise_groups(plan,devices):
    """Fuse same-shape single-consumer chains using typed scalar temporaries.

    Multiple uses in the same consumer compute the producer once. Returned
    intermediates and nodes shared with another consumer are materialized.
    Reductions/scatters are barriers, preserving their accumulation order.
    """
    producers={n.output:n for n in plan.nodes};users=defaultdict(set)
    for n in plan.nodes:
        for i in n.inputs:users[i].add(n.output)
    for i in plan.outputs:users[i].add(None)
    groups={};inlined=set()
    def eligible(n):return n.op in ELEMENTWISE and devices[n.output]=='cpu'
    for node in reversed(plan.nodes):
        if node.output in inlined or not eligible(node):continue
        shape=plan.values[node.output].shape;group=[];seen=set()
        def visit(n):
            if n.output in seen:return
            seen.add(n.output)
            for value in n.inputs:
                child=producers.get(value)
                if (child is not None and eligible(child) and
                    plan.values[value].shape==shape and users[value]=={n.output}):
                    visit(child)
            group.append(n)
        visit(node)
        if len(group)>1:
            groups[node.output]=group
            inlined.update(n.output for n in group[:-1])
    return groups,inlined
