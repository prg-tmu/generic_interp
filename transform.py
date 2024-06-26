import sys
import astpretty
from ast import *


CAN_ENTER_TIER1 = "can_enter_tier1"
WE_ARE_IN_TIER2 = "we_are_in_tier2"

CAN_ENTER_TIER1_BRANCH = "{}_{}".format(CAN_ENTER_TIER1, "branch")
CAN_ENTER_TIER1_RET = "{}_{}".format(CAN_ENTER_TIER1, "ret")
CAN_ENTER_TIER1_JUMP = "{}_{}".format(CAN_ENTER_TIER1, "jump")

CAN_ENTER_TIER1_HINTS = [ CAN_ENTER_TIER1_BRANCH,
                          CAN_ENTER_TIER1_JUMP,
                          CAN_ENTER_TIER1_JUMP
                         ]

class Transformer(object):
    jump_kv = dict()
    branch_kv = dict()
    ret_kv = dict()

    def reset(self):
        self.jump_kv = dict()
        self.branch_kv = dict()
        self.ret_kv = dict()


class InterpVisitor(NodeVisitor, Transformer):
    "For gathering necessary information"

    def get_all_info(self):
        return self.jump_kv, self.branch_kv, self.ret_kv

    def visit_Call(self, node):
        func = node.func
        if isinstance(func, Attribute):
            if func.attr == CAN_ENTER_TIER1_BRANCH:
                kwds = node.keywords
                for kwd in kwds:
                    value = kwd.value
                    delattr(value, 'lineno')
                    delattr(value, 'col_offset')
                    self.branch_kv[kwd.arg] = value
            elif func.attr == CAN_ENTER_TIER1_RET:
                kwds = node.keywords
                for kwd in kwds:
                    value = kwd.value
                    delattr(value, 'lineno')
                    delattr(value, 'col_offset')
                    self.ret_kv[kwd.arg] = value
            elif func.attr == CAN_ENTER_TIER1_JUMP:
                kwds = node.keywords
                for kwd in kwds:
                    value = kwd.value
                    delattr(value, 'lineno')
                    delattr(value, 'col_offset')
                    self.jump_kv[kwd.arg] = value


class TracingTransformer(NodeTransformer, Transformer):
    def __init__(self, node):
        super(TracingTransformer, self).__init__()
        InterpVisitor().visit(node)
        self.node = node

    def transform(self):
        return self.visit(self.node)

    def visit_Expr(self, node):
        value = node.value
        if isinstance(value, Call):
            func = value.func
            if hasattr(func, 'id'):
                if func.id in CAN_ENTER_TIER1:
                    return
        return node

    def visit_If(self, node):
        test = node.test
        body = node.body

        if isinstance(test, Call):
            if hasattr(test.func, 'id'):
                if test.func.id == WE_ARE_IN_TIER2:
                    return body

        self.generic_visit(node)
        return node


class ThreadedTransformer(NodeTransformer, Transformer):
    "For rewriting nodes"

    def __init__(self, node):
        super(ThreadedTransformer, self).__init__()
        InterpVisitor().visit(node)
        self.node = node

    def transform(self):
        return self.visit(self.node)

    def visit_Expr(self, node):
        value = node.value
        if isinstance(value, Call):
            func = value.func
            if func.value.id == "transformer":
                if func.attr == "can_enter_tier1_jump":
                    # print(func.value.id, func.attr)
                    orig_body = Assign(
                        targets=[self.jump_kv['pc']],
                        value=self.jump_kv['target']
                    )
                    new_if = If(test=Call(func=Name(id='we_are_jitted', ctx=Load()),
                                      args=[], keywords=[], starargs=None, kwargs=None),
                                body=[self._create_jitted_jump(orig_body)],
                                orelse=[orig_body])
                    copy_location(new_if, node)
                    fix_missing_locations(new_if)
                    return new_if
                elif func.attr == "can_enter_tier1_ret":
                    orig_body = Return(value=self.ret_kv['ret_value'])
                    new_if = If(test=Call(func=Name(id='we_are_jitted', ctx=Load()),
                                          args=[], keywords=[], starargs=None, kwargs=None),
                                body=[self._create_jitted_ret(orig_body)],
                                orelse=[orig_body])
                    copy_location(new_if, node)
                    fix_missing_locations(new_if)
                    return new_if
                elif func.attr == "can_enter_tier1_branch":
                    orig_body = If(
                        test=Call(func=Name(id='is_true'), ctx=Load(),
                                  args=[], keywords=[], starargs=None, kwargs=None),
                        body=Assign(targets=[self.jump_kv['pc']], value=self.jump_kv['target']),
                        orelse=[]
                    )
                    new_if = If(test=Call(func=Name(id='we_are_jitted', ctx=Load()),
                                          args=[], keywords=[], starargs=None, kwargs=None),
                                body=[self._create_jitted_jump_if(orig_body)],
                                orelse=[orig_body])
                    copy_location(new_if, node)
                    fix_missing_locations(new_if)
                    return new_if

        self.generic_visit(node)
        return node

    def visit_If(self, node):
        test = node.test
        body = node.body
        if isinstance(test, Call):
            if hasattr(test.func, 'id'):
                if test.func.id == WE_ARE_IN_TIER2:
                    kwds = test.keywords
                    assert len(kwds) == 1
                    kwd = kwds[0]
                    assert isinstance(kwd.value, Str), "value %s is not str object" % (dump(kwd.value))
                    if kwd.value.s == 'branch':
                        return
                    elif kwd.value.s == 'ret':
                        return
                    elif kwd.value.s == 'jump':
                        return
                    else:
                        assert False, "unexpected keyword %s" % (kwd.value.s)
        self.generic_visit(node)
        return node

    def _create_jitted_jump(self, orig_body):
        jitted = [
            If(test=Call(func=Name(id='t_is_empty', ctx=Load()),
                         args=[Name(id='tstack', ctx=Load())],
                         keywords=[], starargs=None, kwargs=None),
               body=[
                   Assign(targets=[Name(id='pc', ctx=Load())],
                          value=self.jump_kv['target'])
               ],
               orelse=[
                   Assign(targets=[Tuple(elts=[self.jump_kv['pc'],
                                               Name(id='tstack', ctx=Load())])],
                          value=Call(
                              func=Attribute(value=Name(id='tstack', ctx=Load()),
                                             attr='t_pop', ctx=Load()),
                              args=[], keywords=[], starargs=None, kwargs=None
                          ))
               ]),
            Assign(targets=[self.jump_kv['pc']],
                   value=Call(func=Name(id='emit_jump', ctx=Load()),
                              args=[self.jump_kv['pc'], self.jump_kv['target']],
                              keywords=[], starargs=None, kwargs=None))
        ]
        return jitted

    def _create_jitted_jump_if(self, orig_body):
        jitted = \
            If(test=Call(func=self.branch_kv['cond'],
                         args=[], keywords=[], starargs=[], kwargs=None),
               body=[
                   Assign(targets=[Name(id='tstack', ctx=Store())],
                          value=Call(func=Name(id='t_push', ctx=Load()),
                                     args=[self.branch_kv['false_path'], Name(id='tstack', ctx=Load())],
                                     keywords=[], starargs=None, kwargs=None)),
                   Assign(targets=[Name(id=self.branch_kv['pc'].id, ctx=Store())],
                          value=self.branch_kv['true_path'])
               ],
               orelse=[
                   Assign(targets=[Name(id='tstack', ctx=Store())],
                          value=Call(func=Name(id='t_push', ctx=Load()),
                                     args=[self.branch_kv['true_path'], Name(id='tstack', ctx=Load())],
                                     keywords=[], starargs=None, kwargs=None)),
                   Assign(targets=[Name(id=self.branch_kv['pc'].id, ctx=Store())],
                          value=self.branch_kv['false_path'])
               ])
        return jitted

    def _create_jitted_ret(self, orig_body):
        return \
            If(test=Call(func=Name(id='t_is_empty', ctx=Load()),
                         args=[Name(id='tstack', ctx=Load())],
                         keywords=[], starargs=None, kwargs=None),
               body=[
                   Assign(targets=[Name(id='pc', ctx=Store())],
                          value=Call(func=Name(id='emit_ret', ctx=Load()),
                                     args=[Name(id='pc', ctx=Load()),
                                           self.ret_kv['ret_value']],
                                     keywords=[], starargs=None, kwargs=None)),
                   Expr(
                       value=Call(
                           func=Attribute(
                               value=Name(id='jitdriver', ctx=Load()),
                               attr='can_enter_jit',
                               ctx=Load()
                           ),
                           args=[],
                           keywords=[
                               keyword(arg='pc', value=self.ret_kv['pc']),
                               keyword(arg='bytecode', value=Name(id='bytecode', ctx=Load())),
                               keyword(arg='tstack', value=Name(id='tstack', ctx=Load())),
                               keyword(arg='self', value=Name(id='self', ctx=Load()))
                           ],
                           starargs=None, kwargs=None
                       )
                   )
               ],
               orelse=[
                   Assign(
                       targets=[Tuple(elts=[Name(id='pc', ctx=Store()),
                                            Name(id='tstack', ctx=Store())],
                                      ctx=Store())],
                       value=Call(
                           func=Attribute(value=Name(id='tstack', ctx=Load()),
                                          attr='t_pop', ctx=Load()),
                           args=[], keywords=[], starargs=None, kwargs=None
                       )
                   ),
                   Assign(
                       targets=[Name(id='pc', ctx=Store())],
                       value=Call(
                           func=Name(id='emit_ret', ctx=Load()),
                           args=[
                               Name(id='pc', ctx=Load()),
                               self.ret_kv['ret_value']
                           ],
                           keywords=[], starargs=None, kwargs=None
                       )
                   )
               ])

if __name__ == '__main__':
    import os
    import astunparse
    import ast
    import copy
    from pprint import pprint

    if len(sys.argv) < 2:
        print "Usage: %s filename tier[n]" % (sys.argv[0])
        exit(1)
    fname = sys.argv[1]
    tier = sys.argv[2]
    f = open(fname, 'r')
    tree = parse(f.read())
    f.close()

    if tier == "tier1":
        new_tree = copy.deepcopy(tree)
        threaded_transformer = ThreadedTransformer(tree)
        transformed = threaded_transformer.transform()
        fix_missing_locations(transformed)
        unparsed = astunparse.unparse(transformed)

        new_fname, ext = os.path.splitext(fname)
        new_file = open(new_fname + "_tier1" + ext, 'w')
        new_file.write(unparsed)
        new_file.close()
    elif tier == "tier2":
        new_tree = copy.deepcopy(tree)
        tracing_transformer = TracingTransformer(new_tree)
        transformed = tracing_transformer.transform()
        fix_missing_locations(transformed)
        unparsed = astunparse.unparse(transformed)

        new_fname, ext = os.path.splitext(fname)
        new_file = open(new_fname + "_tier2" + ext, 'w')
        new_file.write(unparsed)
        new_file.close()
    else:
        assert False, "tier1 or tier2 should be specified"
