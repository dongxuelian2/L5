"""Explicitly download and extract predeclared Rieth fault/run selections."""
import argparse
import json
from pathlib import Path
import sys
from time import perf_counter

from l5.tep_import import PROFILES, download_source, prepare_runs


def peak_memory_bytes():
    if sys.platform == 'win32':
        import ctypes
        from ctypes import wintypes
        class Counters(ctypes.Structure):
            _fields_ = [('cb', wintypes.DWORD), ('PageFaultCount', wintypes.DWORD)] + [(name, ctypes.c_size_t) for name in (
                'PeakWorkingSetSize', 'WorkingSetSize', 'QuotaPeakPagedPoolUsage', 'QuotaPagedPoolUsage',
                'QuotaPeakNonPagedPoolUsage', 'QuotaNonPagedPoolUsage', 'PagefileUsage', 'PeakPagefileUsage')]
        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        get_process = ctypes.windll.kernel32.GetCurrentProcess
        get_process.restype = wintypes.HANDLE
        read = ctypes.windll.psapi.GetProcessMemoryInfo
        read.argtypes = (wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD)
        if not read(get_process(), ctypes.byref(counters), counters.cb):
            raise OSError('Unable to read process peak working set.')
        return counters.PeakWorkingSetSize
    import resource
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak if sys.platform == 'darwin' else peak*1024


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-dir', type=Path, required=True)
    parser.add_argument('--cache-dir', type=Path, required=True)
    parser.add_argument('--source', choices=PROFILES, required=True)
    parser.add_argument('--faults', type=int, nargs='+', required=True)
    parser.add_argument('--runs', type=int, nargs='+', required=True)
    parser.add_argument('--download', action='store_true')
    parser.add_argument('--metrics', type=Path, help='Save extraction wall time and process peak resident memory.')
    args = parser.parse_args()
    started = perf_counter()
    if args.download:
        download_source(args.source_dir, args.source)
    result = prepare_runs(args.source_dir, args.cache_dir, args.source, [(f, r) for f in args.faults for r in args.runs])
    print(f'{args.source}: {len(result["runs"])} verified independent runs; {result["source"]["sha256"]}')
    metrics = dict(source=args.source, elapsedSeconds=round(perf_counter()-started, 3), processPeakResidentBytes=peak_memory_bytes(),
                   selectedRuns=len(args.faults)*len(args.runs), parser='rieth-stream-rdx2-v1', extraParserDependencies=[])
    print(json.dumps(metrics))
    if args.metrics:
        args.metrics.parent.mkdir(parents=True, exist_ok=True)
        args.metrics.write_text(json.dumps(metrics, indent=2)+'\n', encoding='utf-8')


if __name__ == '__main__':
    main()
