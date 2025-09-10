import unittest
from collections import Counter
import re

from amaranth import *
from amaranth.sim import *
from amaranth.sim._coverage import *

# If both imports exist across versions, pick one safely
try:
    from amaranth.hdl.ir import Fragment as _AmaranthFragment
except Exception:
    from amaranth.hdl._ir import Fragment as _AmaranthFragment

from amaranth.hdl._ast import (
    Assign as _AstAssign,
    Switch as _AstSwitch,
    Const  as _AstConst,
)

# ======================================================================
#                           COMMON HELPERS
# ======================================================================

_ANCHOR = "chipflow-digital-ip"

def _shorten_filename(filename: str) -> str:
    if not filename:
        return "unknown"
    idx = filename.find(_ANCHOR)
    return filename[idx:] if idx != -1 else filename.split("/")[-1]

def _short_loc(src_loc):
    if not src_loc:
        return "unknown"
    filename, lineno = src_loc[0], src_loc[1]
    return f"{_shorten_filename(filename)}:{lineno}"

def _safe_path_str(parent_path):
    if parent_path:
        return "/".join("anon" if (p is None or p == "") else str(p) for p in parent_path)
    return "top"

def _expr_name(expr):
    # Handles slices/parts, Signals, Consts, and falls back to str(expr)
    if hasattr(expr, "value") and hasattr(expr, "start") and hasattr(expr, "stop"):
        base = _expr_name(expr.value)
        return f"{base}[{expr.start}]" if expr.start == expr.stop - 1 else f"{base}[{expr.start}:{expr.stop}]"
    if hasattr(expr, "name") and expr.name is not None:
        return expr.name
    if hasattr(expr, "value"):  # Const or similar
        try:
            return str(expr.value)
        except Exception:
            pass
    try:
        return str(expr)
    except Exception:
        return f"<expr@{id(expr):x}>"

def _cov_signal_name(prefix: str, parent_path, domain: str, serial: int, *extra) -> str:
    path = "_".join("anon" if p is None else str(p) for p in parent_path) if parent_path else "top"
    suffix = "_".join(str(x) for x in extra) if extra else ""
    return f"{prefix}_{path}_{domain}_{suffix}_{serial}" if suffix else f"{prefix}_{path}_{domain}_{serial}"

def _walk_subfrags(fragment, parent_path, fn):
    """Depth-first walk over fragment + subfragments, calling fn(frag, parent_path)."""
    fn(fragment, parent_path)
    for subfragment, name, _src_loc in getattr(fragment, "subfragments", []):
        if hasattr(subfragment, "statements"):
            _walk_subfrags(subfragment, parent_path + (name,), fn)

# ======================================================================
#                           TOGGLE COVERAGE
# ======================================================================

def collect_all_signals(obj):
    signals = []
    def _collect(o):
        for attr_name in dir(o):
            if attr_name.startswith("_"):
                continue
            try:
                attr = getattr(o, attr_name)
            except Exception:
                continue
            if isinstance(attr, Signal):
                signals.append(attr)
        if hasattr(o, 'submodules'):
            submodules = getattr(o, 'submodules')
            if isinstance(submodules, dict):
                for subm in submodules.values():
                    _collect(subm)
            elif hasattr(submodules, '__iter__'):
                for subm in submodules:
                    _collect(subm)
    _collect(obj)
    return signals

def get_signal_full_paths(design):
    signal_path_map = {}
    for fragment, fragment_info in design.fragments.items():
        fragment_name = ("bench", *fragment_info.name)
        for signal, signal_name in fragment_info.signal_names.items():
            path = "/".join(fragment_name + (signal_name,))
            signal_path_map[id(signal)] = path
    return signal_path_map

# ======================================================================
#                          STATEMENT COVERAGE
# ======================================================================

AGG_STMT_HITS = Counter()
AGG_STMT_INFO = {}

def get_assign_name(domain, stmt):
    loc_str = _short_loc(getattr(stmt, "src_loc", None))
    lhs = _expr_name(stmt.lhs)
    rhs = _expr_name(stmt.rhs)
    return f"{loc_str} | {domain}:{lhs} = {rhs}"

def get_switch_case_name(domain, switch_stmt, patterns, src_loc=None):
    loc_str = _short_loc(src_loc if src_loc is not None else getattr(switch_stmt, "src_loc", None))
    cov_id = getattr(switch_stmt, "_coverage_id", None)
    parent_path = cov_id[0] if cov_id else ()
    path_str = _safe_path_str(parent_path)
    patterns_str = "default" if patterns is None else str(patterns)
    return f"{loc_str} | {path_str} | {domain}:switch_case({patterns_str})"

def tag_all_statements(fragment, coverage_id=0, parent_path=(), stmtid_to_info=None):
    from amaranth.hdl._ast import Assign, Switch
    if stmtid_to_info is None:
        stmtid_to_info = {}

    if not hasattr(fragment, "statements"):
        return coverage_id, stmtid_to_info

    for domain, stmts in fragment.statements.items():
        for stmt in stmts:
            if hasattr(stmt, "_coverage_id"):
                continue
            if isinstance(stmt, Assign):
                stmt._coverage_id = (parent_path, domain, coverage_id)
                stmt._coverage_name = get_assign_name(domain, stmt)
                stmt._coverage_type = "assign"
                stmtid_to_info[stmt._coverage_id] = (stmt._coverage_name, stmt._coverage_type)
                coverage_id += 1

            elif isinstance(stmt, Switch):
                stmt._coverage_id = (parent_path, domain, coverage_id)
                stmt._coverage_name = f"{domain}:switch at {getattr(stmt, 'src_loc', 'unknown')}"
                stmt._coverage_type = "switch"
                stmtid_to_info[stmt._coverage_id] = (stmt._coverage_name, stmt._coverage_type)
                coverage_id += 1

                case_ids = []
                for patterns, sub_stmts, case_src_loc in stmt.cases:
                    case_cov_id = (parent_path, domain, coverage_id)
                    case_name = get_switch_case_name(domain, stmt, patterns, src_loc=case_src_loc)
                    stmtid_to_info[case_cov_id] = (case_name, "switch_case")
                    case_ids.append(case_cov_id)
                    coverage_id += 1
                stmt._coverage_case_ids = tuple(case_ids)

                # Recurse into case bodies
                for patterns, sub_stmts, _case_src_loc in stmt.cases:
                    for sub_stmt in sub_stmts:
                        tmp = type("TempFrag", (), {"statements": {domain: [sub_stmt]}, "subfragments": []})()
                        coverage_id, stmtid_to_info = tag_all_statements(
                            tmp, coverage_id, parent_path, stmtid_to_info
                        )

    # Recurse into subfragments
    for subfragment, name, _ in getattr(fragment, "subfragments", []):
        if hasattr(subfragment, "statements"):
            coverage_id, stmtid_to_info = tag_all_statements(
                subfragment, coverage_id, parent_path + (name,), stmtid_to_info
            )
    return coverage_id, stmtid_to_info

def insert_coverage_signals(fragment):
    from amaranth.hdl._ast import Assign, Const, Signal, Switch as AstSwitch
    coverage_signals = {}

    def inject_in_stmt_list(domain, stmts):
        new = []
        for stmt in stmts:
            # Tag for the statement itself
            if hasattr(stmt, "_coverage_id") and not getattr(stmt, "_coverage_injected", False):
                cov_id = stmt._coverage_id
                typ = getattr(stmt, "_coverage_type", "unknown")
                sig = coverage_signals.get(cov_id)
                if sig is None:
                    sig = Signal(name=_cov_signal_name("cov", cov_id[0], cov_id[1], cov_id[2], typ), init=0)
                    coverage_signals[cov_id] = sig
                new.append(Assign(sig, Const(1)))
                stmt._coverage_injected = True

            new.append(stmt)

            # Tag switch cases & instrument case bodies
            if isinstance(stmt, AstSwitch):
                case_ids = getattr(stmt, "_coverage_case_ids", ())
                for idx, (patterns, sub_stmts, _case_src_loc) in enumerate(stmt.cases):
                    if idx < len(case_ids):
                        case_cov_id = case_ids[idx]
                        case_sig = coverage_signals.get(case_cov_id)
                        if case_sig is None:
                            case_sig = Signal(name=_cov_signal_name("cov", case_cov_id[0], case_cov_id[1], case_cov_id[2], "switch_case"), init=0)
                            coverage_signals[case_cov_id] = case_sig
                        sub_stmts[:0] = [Assign(case_sig, Const(1))]
                    instrumented = inject_in_stmt_list(domain, list(sub_stmts))
                    sub_stmts[:] = instrumented
        return new

    def walk_fragment(frag):
        if not isinstance(frag, _AmaranthFragment):
            return
        for domain, stmts in list(frag.statements.items()):
            frag.statements[domain] = inject_in_stmt_list(domain, list(stmts))
        for subfrag, _name, _ in getattr(frag, "subfragments", []):
            if hasattr(subfrag, "statements"):
                walk_fragment(subfrag)

    walk_fragment(fragment)
    return coverage_signals

def mk_sim_with_stmtcov(dut, verbose=False):
    mod = dut.elaborate(platform=None)
    fragment = _AmaranthFragment.get(mod, platform=None)
    _, stmtid_to_info = tag_all_statements(fragment)
    coverage_signals = insert_coverage_signals(fragment)
    signal_to_stmtid = {id(sig): stmt_id for stmt_id, sig in coverage_signals.items()}
    sim = Simulator(fragment)
    stmt_cov = StatementCoverageObserver(signal_to_stmtid, sim._engine.state, stmtid_to_info=stmtid_to_info)
    sim._engine.add_observer(stmt_cov)
    if verbose:
        print(f"[mk_sim_with_stmtcov] Instrumented {len(stmtid_to_info)} statements for coverage.")
    return sim, stmt_cov, stmtid_to_info, fragment

def merge_stmtcov(results, stmtid_to_info):
    for sid, info in stmtid_to_info.items():
        AGG_STMT_INFO.setdefault(sid, info)
    for sid, hits in results.items():
        AGG_STMT_HITS[sid] += hits

def emit_agg_summary(json_path="i2c_statement_cov.json", label="test_i2c.py"):
    total = len(AGG_STMT_INFO)
    hit = sum(1 for sid in AGG_STMT_INFO if AGG_STMT_HITS.get(sid, 0) > 0)
    pct = 100.0 if total == 0 else (hit / total) * 100.0
    print(f"\n[Statement coverage for {label}] {hit}/{total} = {pct:.1f}%")
    try:
        import json
        report = [{
            "id": str(sid),
            "name": name,
            "type": typ,
            "hits": int(AGG_STMT_HITS.get(sid, 0)),
        } for sid, (name, typ) in AGG_STMT_INFO.items()]
        with open(json_path, "w") as f:
            json.dump({"summary": {"hit": hit, "total": total, "percent": pct},
                       "statements": report}, f, indent=2)
    except Exception as e:
        print(f"(could not write JSON report: {e})")

# ======================================================================
#                           BLOCK COVERAGE
# ======================================================================

AGG_BLOCK_HITS = Counter()
AGG_BLOCK_INFO = {}

def get_block_name(domain, parent_path, tag, src_loc=None):
    path_str = _safe_path_str(parent_path)
    loc_str = _short_loc(src_loc)
    return f"{loc_str} | {path_str} | {domain}:block({tag})"

def tag_all_blocks(fragment, coverage_id=0, parent_path=(), blockid_to_info=None):
    if blockid_to_info is None:
        blockid_to_info = {}
    # Root statement lists
    for domain, stmts in getattr(fragment, "statements", {}).items():
        first_src = getattr(stmts[0], "src_loc", None) if stmts else None
        blk_id = (parent_path, domain, coverage_id)
        blockid_to_info[blk_id] = (get_block_name(domain, parent_path, "root", src_loc=first_src), "block")
        fragment._block_cov_ids = getattr(fragment, "_block_cov_ids", [])
        fragment._block_cov_ids.append((id(stmts), blk_id))
        coverage_id += 1
    # Switch case lists
    for domain, stmts in getattr(fragment, "statements", {}).items():
        for stmt in stmts:
            if isinstance(stmt, _AstSwitch):
                for patterns, sub_stmts, case_src_loc in stmt.cases:
                    blk_id = (parent_path, domain, coverage_id)
                    pat_str = "default" if patterns is None else str(patterns)
                    name = get_block_name(domain, parent_path, f"case:{pat_str}", src_loc=case_src_loc)
                    blockid_to_info[blk_id] = (name, "block")
                    stmt._block_cov_ids = getattr(stmt, "_block_cov_ids", [])
                    stmt._block_cov_ids.append((id(sub_stmts), blk_id))
                    coverage_id += 1
    # Recurse into subfragments
    for subfragment, name, _ in getattr(fragment, "subfragments", []):
        if hasattr(subfragment, "statements"):
            coverage_id, blockid_to_info = tag_all_blocks(
                subfragment, coverage_id, parent_path + (name,), blockid_to_info
            )

    return coverage_id, blockid_to_info

def insert_block_coverage_signals(fragment, blockid_to_info):
    coverage_signals = {}
    listid_to_blockid = {}

    def harvest_block_ids(frag):
        if hasattr(frag, "_block_cov_ids"):
            for list_id, blk_id in frag._block_cov_ids:
                listid_to_blockid[list_id] = blk_id
        for domain, stmts in getattr(frag, "statements", {}).items():
            for stmt in stmts:
                if isinstance(stmt, _AstSwitch) and hasattr(stmt, "_block_cov_ids"):
                    for list_id, blk_id in stmt._block_cov_ids:
                        listid_to_blockid[list_id] = blk_id
        for subfrag, _name, _ in getattr(frag, "subfragments", []):
            if hasattr(subfrag, "statements"):
                harvest_block_ids(subfrag)

    harvest_block_ids(fragment)

    def inject_head(stmts, blk_id):
        if blk_id is None:
            return
        sig = coverage_signals.get(blk_id)
        if sig is None:
            sig = Signal(name=_cov_signal_name("blk", blk_id[0], blk_id[1], blk_id[2]), init=0)
            coverage_signals[blk_id] = sig
        stmts[:0] = [_AstAssign(sig, Const(1))]

    def walk_fragment(frag):
        if not isinstance(frag, _AmaranthFragment):
            return
        for _domain, stmts in list(frag.statements.items()):
            inject_head(stmts, listid_to_blockid.get(id(stmts)))
            for stmt in stmts:
                if isinstance(stmt, _AstSwitch):
                    for _patterns, sub_stmts, _case_src_loc in stmt.cases:
                        inject_head(sub_stmts, listid_to_blockid.get(id(sub_stmts)))
        for subfrag, _name, _ in getattr(frag, "subfragments", []):
            if hasattr(subfrag, "statements"):
                walk_fragment(subfrag)

    walk_fragment(fragment)
    return coverage_signals

def mk_sim_with_blockcov(dut, verbose=False):
    mod = dut.elaborate(platform=None)
    fragment = _AmaranthFragment.get(mod, platform=None)
    _, blockid_to_info = tag_all_blocks(fragment)
    coverage_signals = insert_block_coverage_signals(fragment, blockid_to_info)
    signal_to_blockid = {id(sig): blk_id for blk_id, sig in coverage_signals.items()}
    sim = Simulator(fragment)
    blk_cov = BlockCoverageObserver(signal_to_blockid, sim._engine.state, blockid_to_info=blockid_to_info)
    sim._engine.add_observer(blk_cov)
    if verbose:
        print(f"[mk_sim_with_blockcov] Instrumented {len(blockid_to_info)} blocks for coverage.")
    return sim, blk_cov, blockid_to_info, fragment

def merge_blockcov(results, blockid_to_info):
    for bid, info in blockid_to_info.items():
        AGG_BLOCK_INFO.setdefault(bid, info)
    for bid, hits in results.items():
        AGG_BLOCK_HITS[bid] += hits

def emit_agg_block_summary(json_path="i2c_block_cov.json", label="test_i2c.py",
                           show_hits=True, show_misses=True, max_print=None, sort_by="name"):
    total = len(AGG_BLOCK_INFO)
    hit = sum(1 for bid in AGG_BLOCK_INFO if AGG_BLOCK_HITS.get(bid, 0) > 0)
    pct = 100.0 if total == 0 else (hit / total) * 100.0
    print(f"\n[Block coverage for {label}] {hit}/{total} = {pct:.1f}%")
    try:
        import json
        report = [{
            "id": str(bid),
            "name": name,
            "type": typ,
            "hits": int(AGG_BLOCK_HITS.get(bid, 0)),
        } for bid, (name, typ) in AGG_BLOCK_INFO.items()]
        with open(json_path, "w") as f:
            json.dump({"summary": {"hit": hit, "total": total, "percent": pct},
                       "blocks": report}, f, indent=2)
    except Exception as e:
        print(f"(could not write JSON report: {e})")

# ======================================================================
#                         ASSERTION COVERAGE
# ======================================================================

AGG_ASSERT_HITS = Counter()
AGG_ASSERT_INFO = {}

def _assert_node_kind(node):
    kind = getattr(node, "kind", None)
    if kind is not None:
        val = getattr(kind, "value", kind)
        if isinstance(val, str):
            v = val.lower()
            if v in ("assert", "assume", "cover"):
                return v
    n = type(node).__name__.lower()
    if "assert" in n: return "assert"
    if "assume" in n: return "assume"
    if "cover"  in n: return "cover"
    return None

def _is_assert_like(node):
    return _assert_node_kind(node) is not None

def _cond_of(node):
    for attr in ("cond", "test", "expr"):
        c = getattr(node, attr, None)
        if c is not None:
            return c
    return None

def get_assert_name(domain, node, parent_path=()):
    loc = _short_loc(getattr(node, "src_loc", None))
    typ = getattr(node, "_assert_type", None) or getattr(getattr(node, "kind", None), "value", None) or "assert"
    cond = _cond_of(node)
    cond_s = _expr_name(cond) if cond is not None else "?"
    return f"{loc} | {_safe_path_str(parent_path)} | {domain}:{typ}({cond_s})"

def _iter_stmts_container(x):
    if x is None:
        return
    if isinstance(x, (list, tuple, set, frozenset)):
        for s in x:
            yield s
    elif isinstance(x, dict):
        for s in x.values():
            yield s
    else:
        yield x

def _iter_child_objs(obj):
    if obj is None:
        return
    if isinstance(obj, (list, tuple, set, frozenset)):
        for it in obj:
            yield it
        return
    if isinstance(obj, dict):
        for it in obj.values():
            yield it
        return
    d = getattr(obj, "__dict__", None)
    if d:
        for v in d.values():
            yield v
    for slot in getattr(type(obj), "__slots__", ()):
        try:
            yield getattr(obj, slot)
        except Exception:
            pass

def _walk_stmt(stmt, visit, _seen=None):
    if stmt is None:
        return
    if _seen is None:
        _seen = set()
    oid = id(stmt)
    if oid in _seen:
        return
    _seen.add(oid)
    visit(stmt)
    for child in _iter_child_objs(stmt):
        _walk_stmt(child, visit, _seen)

def _iter_formal_roots(fragment):
    for nm in dir(fragment):
        lnm = nm.lower()
        if lnm in ("asserts", "assumes", "covers") or ("formal" in lnm):
            try:
                val = getattr(fragment, nm)
            except Exception:
                continue
            if val is not None:
                yield nm, val

def tag_all_asserts(fragment, coverage_id=0, parent_path=(), assertid_to_info=None, found_nodes=None):
    if assertid_to_info is None:
        assertid_to_info = {}
    if found_nodes is None:
        found_nodes = {}
    if not hasattr(fragment, "statements"):
        return coverage_id, assertid_to_info, found_nodes

    for domain, stmts in fragment.statements.items():
        for root in _iter_stmts_container(stmts):
            def visit(s):
                nonlocal coverage_id
                if _is_assert_like(s) and not hasattr(s, "_assert_id"):
                    s._assert_id = (parent_path, domain, coverage_id)
                    s._assert_type = _assert_node_kind(s) or "assert"
                    s._assert_name = get_assert_name(domain, s, parent_path)
                    assertid_to_info[s._assert_id] = (s._assert_name, s._assert_type)
                    found_nodes[s._assert_id] = (fragment, domain, s)
                    coverage_id += 1
            _walk_stmt(root, visit)

    for _nm, container in _iter_formal_roots(fragment):
        if isinstance(container, dict):
            for key, nodes in container.items():
                domain = key if isinstance(key, str) else "sync"
                for root in _iter_stmts_container(nodes):
                    def visit(s):
                        nonlocal coverage_id
                        if _is_assert_like(s) and not hasattr(s, "_assert_id"):
                            s._assert_id = (parent_path, domain, coverage_id)
                            s._assert_type = _assert_node_kind(s) or "assert"
                            s._assert_name = get_assert_name(domain, s, parent_path)
                            assertid_to_info[s._assert_id] = (s._assert_name, s._assert_type)
                            found_nodes[s._assert_id] = (fragment, domain, s)
                            coverage_id += 1
                    _walk_stmt(root, visit)
        else:
            domain = "sync"
            for root in _iter_stmts_container(container):
                def visit(s):
                    nonlocal coverage_id
                    if _is_assert_like(s) and not hasattr(s, "_assert_id"):
                        s._assert_id = (parent_path, domain, coverage_id)
                        s._assert_type = _assert_node_kind(s) or "assert"
                        s._assert_name = get_assert_name(domain, s, parent_path)
                        assertid_to_info[s._assert_id] = (s._assert_name, s._assert_type)
                        found_nodes[s._assert_id] = (fragment, domain, s)
                        coverage_id += 1
                _walk_stmt(root, visit)

    for subfragment, name, _ in getattr(fragment, "subfragments", []):
        if hasattr(subfragment, "statements"):
            coverage_id, assertid_to_info, found_nodes = tag_all_asserts(
                subfragment, coverage_id, parent_path + (name,), assertid_to_info, found_nodes
            )
    return coverage_id, assertid_to_info, found_nodes

def insert_assert_coverage_signals(fragment, found_nodes):
    coverage_signal_map = {}

    def make_sig(aid, typ, outcome):
        s = Signal(name=_cov_signal_name("cov", aid[0], aid[1], aid[2], typ, outcome), init=0)
        coverage_signal_map[id(s)] = (aid, outcome)
        return s

    def truthy(expr):
        try:
            return expr != Const(0)
        except Exception:
            return expr

    for aid, (frag_of_node, domain, node) in found_nodes.items():
        typ = getattr(node, "_assert_type", "assert")
        c = _cond_of(node)
        if c is None:
            continue
        t = truthy(c)
        dom_list = list(frag_of_node.statements.get(domain, []))

        if typ in ("assert", "assume"):
            s_true  = make_sig(aid, typ, "true")
            s_false = make_sig(aid, typ, "false")
            s_fail  = make_sig(aid, typ, "fail")
            dom_list += [s_true.eq(t), s_false.eq(~t), s_fail.eq(~t)]
        elif typ == "cover":
            s_true = make_sig(aid, typ, "true")
            dom_list += [s_true.eq(t)]

        frag_of_node.statements[domain] = dom_list

    return coverage_signal_map

def mk_sim_with_assertcov(dut, verbose=False):
    fragment = _AmaranthFragment.get(dut, platform=None) if hasattr(dut, "statements") else _AmaranthFragment.get(dut, platform=None)
    _, assertid_to_info, found_nodes = tag_all_asserts(fragment)
    coverage_signal_map = insert_assert_coverage_signals(fragment, found_nodes)
    assert_cov = AssertionCoverageObserver(coverage_signal_map, None, assertid_to_info=assertid_to_info)
    sim = Simulator(fragment)
    assert_cov.state = sim._engine.state
    sim._engine.add_observer(assert_cov)
    if verbose:
        print(f"[mk_sim_with_assertcov] Instrumented {len(assertid_to_info)} assertion-like nodes.")
    return sim, assert_cov, assertid_to_info, fragment

def merge_assertcov(results, assertid_to_info):
    for aid, info in assertid_to_info.items():
        AGG_ASSERT_INFO.setdefault(aid, info)
    for aid, buckets in results.items():
        for outcome, hits in buckets.items():
            if hits:
                AGG_ASSERT_HITS[(aid, outcome)] += hits

def emit_agg_assert_summary(json_path="i2c_assertion_cov.json", label="test_i2c.py"):
    node_ids = list({aid for (aid, _out) in AGG_ASSERT_HITS} | set(AGG_ASSERT_INFO.keys()))
    node_ids.sort(key=lambda x: (AGG_ASSERT_INFO.get(x, ("", ""))[0]))
    total_nodes = len(node_ids)
    any_activity = sum(1 for aid in node_ids
                       if (AGG_ASSERT_HITS.get((aid, "true"), 0) +
                           AGG_ASSERT_HITS.get((aid, "false"), 0) +
                           AGG_ASSERT_HITS.get((aid, "fail"), 0)) > 0)
    pct = 100.0 if total_nodes == 0 else (any_activity / total_nodes) * 100.0
    print(f"\n[Assertion coverage for {label}] {any_activity}/{total_nodes} = {pct:.1f}%")
    try:
        import json
        report = []
        for aid in node_ids:
            name, typ = AGG_ASSERT_INFO.get(aid, ("<unknown>", "<unknown>"))
            rec = {
                "id": str(aid),
                "name": name,
                "type": typ,
                "true": int(AGG_ASSERT_HITS.get((aid, "true"), 0)),
                "false": int(AGG_ASSERT_HITS.get((aid, "false"), 0)),
                "fail": int(AGG_ASSERT_HITS.get((aid, "fail"), 0)),
            }
            report.append(rec)
        with open(json_path, "w") as f:
            json.dump({"summary": {"active": any_activity, "total": total_nodes, "percent": pct},
                       "assertions": report}, f, indent=2)
    except Exception as e:
        print(f"(could not write JSON report: {e})")

def emit_assert_summary(json_path="i2c_assertion_cov.json", label="test_i2c.py"):
    return emit_agg_assert_summary(json_path=json_path, label=label)

# ======================================================================
#                        EXPRESSION COVERAGE
# ======================================================================

AGG_EXPR_HITS = Counter()
AGG_EXPR_INFO = {}

def _is_bool_width(expr):
    try:
        return int(expr.shape().width) == 1
    except Exception:
        return False

def _src_loc_str(node):
    return _short_loc(getattr(node, "src_loc", None))

def _cov_name_for_expr(cov_id, domain, parent_path, suffix):
    return _cov_signal_name("cov", parent_path, domain, cov_id, "expr", suffix)

def _iter_boolean_subexpressions_from_assign(stmt):
    stack = [stmt.rhs]
    seen = set()
    while stack:
        e = stack.pop()
        if id(e) in seen:
            continue
        seen.add(id(e))
        if _is_bool_width(e):
            yield e
        for attr in ("operands", "value", "test", "cases", "choices"):
            sub = getattr(e, attr, None)
            if sub is None:
                continue
            if isinstance(sub, (list, tuple)):
                stack.extend(s for s in sub if s is not None)
            else:
                stack.append(sub)

def _pattern_to_mask_value(pattern_str, width):
    if not re.fullmatch(r"[01-]+", pattern_str):
        raise ValueError(f"Unsupported switch pattern string: {pattern_str!r}")
    if len(pattern_str) != width:
        raise ValueError(f"Pattern width {len(pattern_str)} != test width {width}")
    mask = value = 0
    for ch in pattern_str:
        mask <<= 1; value <<= 1
        if ch == "-":
            pass
        elif ch == "0":
            mask |= 1
        elif ch == "1":
            mask |= 1; value |= 1
        else:
            raise ValueError(f"Bad pattern char {ch!r}")
    return mask, value

def _match_case(test, p):
    if isinstance(p, _AstConst):
        return test == p
    try:
        return test == Const(int(p), shape=test.shape())
    except Exception:
        pass
    if isinstance(p, str):
        mask_int, value_int = _pattern_to_mask_value(p, int(test.shape().width))
        mask = Const(mask_int, shape=test.shape())
        value = Const(value_int, shape=test.shape())
        return (test & mask) == value
    return test == Const(p, shape=test.shape())

from functools import reduce
from operator import or_ as _bor

def _boolean_exprs_from_switch(switch_stmt):
    test = switch_stmt.test
    if test is None:
        return []
    bool_exprs = []
    any_match = None
    for patterns, _sub_stmts, _case_src_loc in switch_stmt.cases:
        if patterns is None:
            continue
        pats = patterns if isinstance(patterns, (list, tuple)) else (patterns,)
        eqs = [_match_case(test, p) for p in pats]
        expr_case = reduce(_bor, eqs) if len(eqs) > 1 else eqs[0]
        bool_exprs.append(("case", expr_case, patterns))
        any_match = expr_case if any_match is None else (any_match | expr_case)
    if any_match is not None:
        bool_exprs.append(("default", ~any_match, None))
    return bool_exprs

def tag_all_expressions(fragment, coverage_id=0, parent_path=(), exprid_to_info=None):
    if exprid_to_info is None:
        exprid_to_info = {}
    if not hasattr(fragment, "statements"):
        return coverage_id, exprid_to_info

    for domain, stmts in fragment.statements.items():
        for stmt in stmts:
            if isinstance(stmt, _AstAssign):
                src = _src_loc_str(stmt)
                for e in _iter_boolean_subexpressions_from_assign(stmt):
                    if hasattr(e, "_expr_coverage_id"):
                        continue
                    expr_name = f"{src} | {domain}:expr({_expr_name(e)})"
                    e._expr_coverage_id = (parent_path, domain, coverage_id)
                    e._expr_coverage_name = expr_name
                    exprid_to_info[e._expr_coverage_id] = (expr_name, "expr")
                    coverage_id += 1
            elif isinstance(stmt, _AstSwitch):
                src = _src_loc_str(stmt)
                for role, e, patterns in _boolean_exprs_from_switch(stmt):
                    if hasattr(e, "_expr_coverage_id"):
                        continue
                    patt_str = "default" if patterns is None else str(patterns)
                    expr_name = f"{src} | {domain}:switch_{role}({patt_str})"
                    e._expr_coverage_id = (parent_path, domain, coverage_id)
                    e._expr_coverage_name = expr_name
                    exprid_to_info[e._expr_coverage_id] = (expr_name, "expr")
                    coverage_id += 1

    for subfragment, name, _ in getattr(fragment, "subfragments", []):
        if hasattr(subfragment, "statements"):
            coverage_id, exprid_to_info = tag_all_expressions(
                subfragment, coverage_id, parent_path + (name,), exprid_to_info
            )
    return coverage_id, exprid_to_info

def insert_expression_coverage_signals(fragment):
    coverage_signals = {}

    def _inject_in_stmt_list(domain, stmts, parent_path):
        new_list = []
        for stmt in stmts:
            if isinstance(stmt, _AstAssign):
                for e in _iter_boolean_subexpressions_from_assign(stmt):
                    if not hasattr(e, "_expr_coverage_id"):
                        continue
                    cov_id = e._expr_coverage_id
                    t_sig = coverage_signals.get((cov_id, "T"))
                    if t_sig is None:
                        t_sig = Signal(name=_cov_name_for_expr(cov_id[2], cov_id[1], cov_id[0], "T"), init=0)
                        coverage_signals[(cov_id, "T")] = t_sig
                    f_sig = coverage_signals.get((cov_id, "F"))
                    if f_sig is None:
                        f_sig = Signal(name=_cov_name_for_expr(cov_id[2], cov_id[1], cov_id[0], "F"), init=0)
                        coverage_signals[(cov_id, "F")] = f_sig
                    new_list.append(_AstAssign(t_sig, e))
                    new_list.append(_AstAssign(f_sig, ~e))
                new_list.append(stmt)

            elif isinstance(stmt, _AstSwitch):
                for role, e, _patterns in _boolean_exprs_from_switch(stmt):
                    if not hasattr(e, "_expr_coverage_id"):
                        continue
                    cov_id = e._expr_coverage_id
                    t_sig = coverage_signals.get((cov_id, "T"))
                    if t_sig is None:
                        t_sig = Signal(name=_cov_name_for_expr(cov_id[2], cov_id[1], cov_id[0], "T"), init=0)
                        coverage_signals[(cov_id, "T")] = t_sig
                    f_sig = coverage_signals.get((cov_id, "F"))
                    if f_sig is None:
                        f_sig = Signal(name=_cov_name_for_expr(cov_id[2], cov_id[1], cov_id[0], "F"), init=0)
                        coverage_signals[(cov_id, "F")] = f_sig
                    new_list.append(_AstAssign(t_sig, e))
                    new_list.append(_AstAssign(f_sig, ~e))
                if hasattr(stmt, "cases"):
                    for idx, (patterns, sub_stmts, _case_src_loc) in enumerate(stmt.cases):
                        instrumented = _inject_in_stmt_list(domain, list(sub_stmts), parent_path)
                        sub_stmts[:] = instrumented
                new_list.append(stmt)
            else:
                new_list.append(stmt)
        return new_list

    def _walk_fragment(frag, parent_path):
        if not isinstance(frag, _AmaranthFragment):
            return
        for domain, stmts in list(frag.statements.items()):
            frag.statements[domain] = _inject_in_stmt_list(domain, list(stmts), parent_path)
        for subfrag, name, _ in getattr(frag, "subfragments", []):
            if hasattr(subfrag, "statements"):
                _walk_fragment(subfrag, parent_path + (name,))

    _walk_fragment(fragment, ())
    return coverage_signals

def mk_sim_with_exprcov(dut, verbose=False):
    mod = dut.elaborate(platform=None)
    fragment = _AmaranthFragment.get(mod, platform=None)
    _, exprid_to_info = tag_all_expressions(fragment)
    cov_sigs = insert_expression_coverage_signals(fragment)
    coverage_signal_map = {id(sig): (expr_cov_id, outcome) for (expr_cov_id, outcome), sig in cov_sigs.items()}
    sim = Simulator(fragment)
    expr_cov = ExpressionCoverageObserver(coverage_signal_map, sim._engine.state, exprid_to_info=exprid_to_info)
    sim._engine.add_observer(expr_cov)
    if verbose:
        total_exprs = len({eid for (eid, _outcome) in cov_sigs.keys()})
        print(f"[mk_sim_with_exprcov] Instrumented {total_exprs} boolean sub-expressions ({len(cov_sigs)} signals for T/F).")
    return sim, expr_cov, exprid_to_info, fragment

def merge_exprcov(results, exprid_to_info):
    for eid, info in exprid_to_info.items():
        AGG_EXPR_INFO.setdefault(eid, info)
    for eid, tf in results.items():
        AGG_EXPR_HITS[(eid, "T")] += int(tf.get("T", 0))
        AGG_EXPR_HITS[(eid, "F")] += int(tf.get("F", 0))

def emit_expr_summary(json_path="i2c_expression_cov.json", label="test_i2c.py"):
    total = len(AGG_EXPR_INFO)
    hit = sum(1 for eid in AGG_EXPR_INFO
              if AGG_EXPR_HITS.get((eid, "T"), 0) > 0 and AGG_EXPR_HITS.get((eid, "F"), 0) > 0)
    pct = 100.0 if total == 0 else (hit / total) * 100.0
    print(f"\n[Expression coverage for {label}] {hit}/{total} = {pct:.1f}%")
    try:
        import json
        report = []
        for eid, (name, typ) in AGG_EXPR_INFO.items():
            t = int(AGG_EXPR_HITS.get((eid, "T"), 0))
            f = int(AGG_EXPR_HITS.get((eid, "F"), 0))
            report.append({
                "id": str(eid),
                "name": name,
                "type": typ,
                "true_hits": t,
                "false_hits": f,
                "covered": bool(t > 0 and f > 0),
            })
        with open(json_path, "w") as f:
            json.dump({"summary": {"hit": hit, "total": total, "percent": pct},
                       "expressions": report}, f, indent=2)
    except Exception as e:
        print(f"(could not write JSON report: {e})")


def mk_sim_with_all_cov(dut, verbose=False, label=None):
    from amaranth.hdl._ir import Fragment as _AmaranthFragment

    mod = dut.elaborate(platform=None)
    fragment = _AmaranthFragment.get(mod, platform=None)

    _, stmt_info = tag_all_statements(fragment)
    _, blk_info  = tag_all_blocks(fragment)
    _, assert_info, assert_nodes = tag_all_asserts(fragment)
    _, expr_info = tag_all_expressions(fragment)

    stmt_sigs = insert_coverage_signals(fragment)
    blk_sigs  = insert_block_coverage_signals(fragment, blk_info)
    assert_sigmap = insert_assert_coverage_signals(fragment, assert_nodes)
    expr_sigs = insert_expression_coverage_signals(fragment)
    expr_map = {id(sig): (expr_id, outcome) for (expr_id, outcome), sig in expr_sigs.items()}

    sim = Simulator(fragment)

    stmt_cov   = StatementCoverageObserver({id(sig): sid for sid, sig in stmt_sigs.items()},
                                           sim._engine.state, stmtid_to_info=stmt_info)
    blk_cov    = BlockCoverageObserver({id(sig): bid for bid, sig in blk_sigs.items()},
                                       sim._engine.state, blockid_to_info=blk_info)
    assert_cov = AssertionCoverageObserver(assert_sigmap, sim._engine.state,
                                           assertid_to_info=assert_info)
    expr_cov   = ExpressionCoverageObserver(expr_map, sim._engine.state,
                                            exprid_to_info=expr_info)

    sim._engine.add_observer(stmt_cov)
    sim._engine.add_observer(blk_cov)
    sim._engine.add_observer(assert_cov)
    sim._engine.add_observer(expr_cov)

    if verbose:
        prefix = f"[{label}] " if label else "[mk_sim_with_all_cov]"
        print(f"{prefix} stmts={len(stmt_info)}, blocks={len(blk_info)}, "
              f"asserts={len(assert_info)}, exprs={len(expr_info)}")

    return sim, {
        "stmt": (stmt_cov, stmt_info),
        "blk":  (blk_cov,  blk_info),
        "assert": (assert_cov, assert_info),
        "expr": (expr_cov, expr_info),
    }
