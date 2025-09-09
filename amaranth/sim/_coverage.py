from enum import Enum, auto
from ._base import Observer
from amaranth.sim._vcdwriter import eval_value, eval_format

class ToggleDirection(Enum):
    ZERO_TO_ONE = auto()
    ONE_TO_ZERO = auto()

class ToggleCoverageObserver(Observer):
    def __init__(self, state, signal_path_map=None, **kwargs):
        self.state = state
        self._prev_values = {}
        self._toggles = {}
        self._signal_names = {}
        self._signal_path_map = signal_path_map or {}
        super().__init__(**kwargs)

    def update_signal(self, timestamp, signal):
        sig_id = id(signal)
        try:
            val = eval_value(self.state, signal)
        except (KeyError, AttributeError): 
            val = int(self.state.get_signal(signal))
        try:
            curr_val = int(val)
        except TypeError:
            curr_val = val

        if sig_id not in self._prev_values:
            self._prev_values[sig_id] = curr_val
            self._toggles[sig_id] = {
                i: {ToggleDirection.ZERO_TO_ONE: 0, ToggleDirection.ONE_TO_ZERO: 0}
                for i in range(signal.shape().width)
            }
            self._signal_names[sig_id] = self._signal_path_map.get(sig_id, signal.name)
            return

        prev_val = self._prev_values[sig_id]

        for bit in range(signal.shape().width):
            prev_bit = (prev_val >> bit) & 1
            curr_bit = (curr_val >> bit) & 1
            if prev_bit == 0 and curr_bit == 1:
                self._toggles[sig_id][bit][ToggleDirection.ZERO_TO_ONE] += 1
            elif prev_bit == 1 and curr_bit == 0:
                self._toggles[sig_id][bit][ToggleDirection.ONE_TO_ZERO] += 1

        self._prev_values[sig_id] = curr_val

    def update_memory(self, timestamp, memory, addr):
        pass 

    def get_results(self):
        return {
            self._signal_names[sig_id]: toggles
            for sig_id, toggles in self._toggles.items()
        }

    def close(self, timestamp):
        results = self.get_results()
        print("=== Toggle Coverage Report ===")
        for signal, bit_toggles in results.items():
            print(f"{signal}:")
            for bit, counts in bit_toggles.items():
                print(f"  Bit {bit}: 0→1={counts[ToggleDirection.ZERO_TO_ONE]}, 1→0={counts[ToggleDirection.ONE_TO_ZERO]}")



class StatementCoverageObserver(Observer):
    def __init__(self, coverage_signal_map, state, stmtid_to_info=None, **kwargs):
        self.coverage_signal_map = coverage_signal_map
        self.state = state
        self.stmtid_to_info = stmtid_to_info or {}
        self._statement_hits = {}
        super().__init__(**kwargs)

    def update_signal(self, timestamp, signal):
        sig_id = id(signal)
        if sig_id in self.coverage_signal_map:
            stmt_id = self.coverage_signal_map[sig_id]
            self._statement_hits[stmt_id] = self._statement_hits.get(stmt_id, 0) + 1

    def update_memory(self, timestamp, memory, addr):
        pass

    def get_results(self):
        return self._statement_hits

    def close(self, timestamp):
        pass



class BlockCoverageObserver(Observer):
    def __init__(self, coverage_signal_map, state, blockid_to_info=None, **kwargs):
        self.coverage_signal_map = coverage_signal_map
        self.state = state
        self.blockid_to_info = blockid_to_info or {}
        self._block_hits = {}
        super().__init__(**kwargs)

    def update_signal(self, timestamp, signal):
        sig_id = id(signal)
        if sig_id in self.coverage_signal_map:
            block_id = self.coverage_signal_map[sig_id]
            self._block_hits[block_id] = self._block_hits.get(block_id, 0) + 1

    def update_memory(self, timestamp, memory, addr):
        pass

    def get_results(self):
        return self._block_hits

    def close(self, timestamp):
        pass



class AssertionCoverageObserver(Observer):
    def __init__(self, coverage_signal_map, state, assertid_to_info=None, **kwargs):
        self.coverage_signal_map = coverage_signal_map
        self.state = state
        self.assertid_to_info = assertid_to_info or {}
        self._assert_hits = {}
        super().__init__(**kwargs)

    def update_signal(self, timestamp, signal):
        sig_id = id(signal)
        if sig_id in self.coverage_signal_map:
            assert_id, outcome = self.coverage_signal_map[sig_id]
            bucket = self._assert_hits.get(assert_id)
            if bucket is None:
                bucket = {"true": 0, "false": 0, "fail": 0}
                self._assert_hits[assert_id] = bucket
            bucket[outcome] = bucket.get(outcome, 0) + 1

    def update_memory(self, timestamp, memory, addr):
        pass

    def get_results(self):
        return self._assert_hits

    def close(self, timestamp):
        pass

class ExpressionCoverageObserver(Observer):
    def __init__(self, coverage_signal_map, state, exprid_to_info=None, **kwargs):
        self.coverage_signal_map = coverage_signal_map
        self.state = state
        self.exprid_to_info = exprid_to_info or {}
        self._expr_hits = {}
        super().__init__(**kwargs)
    def update_signal(self, timestamp, signal):
        sig_id = id(signal)
        if sig_id in self.coverage_signal_map:
            expr_id, outcome = self.coverage_signal_map[sig_id]
            key = (expr_id, outcome)
            self._expr_hits[key] = self._expr_hits.get(key, 0) + 1
    def update_memory(self, timestamp, memory, addr):
        pass
    def get_results(self):
        results = {}
        for (expr_id, outcome), hits in self._expr_hits.items():
            bucket = results.setdefault(expr_id, {"T": 0, "F": 0})
            bucket[outcome] += hits
        return results
    def close(self, timestamp):
        pass
