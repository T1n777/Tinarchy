#!/usr/bin/env python3
"""
Tinarchy Universal Dynamic Network & Multicore Autotuner
Auto-detects CPU topology, enables multicore RPS/RFS packet steering,
and adaptively fine-tunes queues based on live network telemetry.
"""
import subprocess
import os
import sys
import time
import re
import json
import glob
from datetime import datetime

LOG_FILE = "/var/log/tinarchy/net-tuning.log"

def get_cpu_mask():
    """Dynamically compute hex CPU bitmask for all online cores."""
    cpus = os.cpu_count() or 4
    mask = (1 << cpus) - 1
    return f"{mask:x}"

def apply_multicore_rps():
    """Dynamically discover network queues and apply RPS/RFS across all cores."""
    mask = get_cpu_mask()
    actions = []
    for rx_path in glob.glob("/sys/class/net/*/queues/rx-*"):
        parts = rx_path.split('/')
        iface = parts[4]
        q_name = parts[6]
        if iface == "lo":
            continue
        try:
            with open(f"{rx_path}/rps_cpus", "w") as f:
                f.write(mask)
            with open(f"{rx_path}/rps_flow_cnt", "w") as f:
                f.write("4096")
            actions.append(f"{iface}/{q_name}: RPS mask={mask}, RFS=4096")
        except Exception as e:
            actions.append(f"{iface}/{q_name} RPS error: {e}")
    return actions

def get_live_flows():
    """Extract TCP socket telemetry from ss for Tailscale peers (100.64.0.0/10)."""
    try:
        res = subprocess.run(
            ["ss", "-tino", "dst", "100.64.0.0/10"],
            capture_output=True, text=True, timeout=3
        )
    except Exception:
        return []

    flows = []
    lines = res.stdout.strip().split('\n')
    for i in range(0, len(lines), 2):
        if i + 1 < len(lines):
            header = lines[i]
            details = lines[i + 1]
            bw_m = re.search(r'bw:(\d+)bps', details)
            rtt_m = re.search(r'rtt:([\d\.]+)/([\d\.]+)', details)
            minrtt_m = re.search(r'minrtt:([\d\.]+)', details)
            retrans_m = re.search(r'bytes_retrans:(\d+)', details)
            sent_m = re.search(r'bytes_sent:(\d+)', details)

            flows.append({
                'bw': int(bw_m.group(1)) if bw_m else 0,
                'rtt': float(rtt_m.group(1)) if rtt_m else 0.0,
                'minrtt': float(minrtt_m.group(1)) if minrtt_m else 0.0,
                'retrans': int(retrans_m.group(1)) if retrans_m else 0,
                'sent': int(sent_m.group(1)) if sent_m else 1,
            })
    return flows

def get_txqueuelen(iface="tailscale0"):
    try:
        out = subprocess.check_output(
            f"ip link show {iface} | grep -o 'qlen [0-9]*' | awk '{{print $2}}'",
            shell=True, text=True
        ).strip()
        return int(out)
    except Exception:
        return 500

def set_txqueuelen(iface, new_qlen):
    clamped = max(500, min(2000, new_qlen))
    try:
        subprocess.run(["ip", "link", "set", iface, "txqueuelen", str(clamped)], check=True)
        return clamped
    except Exception:
        return None

def log_event(message):
    try:
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        with open(LOG_FILE, 'a') as f:
            f.write(f"[{timestamp}] {message}\n")
    except Exception:
        pass

def run_cycle(state):
    flows = get_live_flows()
    if not flows:
        return state

    total_sent = sum(f['sent'] for f in flows)
    total_retrans = sum(f['retrans'] for f in flows)
    peak_bw = max(f['bw'] for f in flows)
    active_rtts = [f['rtt'] for f in flows if f['rtt'] > 0]
    active_minrtts = [f['minrtt'] for f in flows if f['minrtt'] > 0]

    avg_rtt = sum(active_rtts) / len(active_rtts) if active_rtts else 0.0
    avg_minrtt = sum(active_minrtts) / len(active_minrtts) if active_minrtts else 0.0

    loss_ratio = (total_retrans / total_sent) if total_sent > 0 else 0.0
    rtt_inflation = (avg_rtt / avg_minrtt) if avg_minrtt > 0 else 1.0
    cur_q = get_txqueuelen("tailscale0")

    if rtt_inflation > 2.2 or loss_ratio > 0.005:
        if cur_q > 500:
            new_q = set_txqueuelen("tailscale0", cur_q - 100)
            log_event(f"Bufferbloat mitigated: txqueuelen {cur_q} -> {new_q} (Inflation: {rtt_inflation:.1f}x, Loss: {loss_ratio*100:.2f}%)")
    elif loss_ratio == 0.0 and rtt_inflation < 1.25 and peak_bw > 25_000_000:
        if cur_q < 2000:
            new_q = set_txqueuelen("tailscale0", cur_q + 100)
            log_event(f"Throughput expanded: txqueuelen {cur_q} -> {new_q} (BW: {peak_bw/1e6:.1f} Mbps)")

    state['peak_bw'] = max(state.get('peak_bw', 0), peak_bw)
    state['last_rtt'] = avg_rtt
    state['last_loss'] = loss_ratio
    state['last_qlen'] = cur_q
    return state

def main():
    rps_actions = apply_multicore_rps()
    init_msg = f"Universal Tuner initialized. Multicore setup: {', '.join(rps_actions)}"
    print(init_msg)
    log_event(init_msg)

    if "--run-once" in sys.argv:
        state = run_cycle({'peak_bw': 0})
        print(f"One-shot complete: {json.dumps(state)}")
        return

    state = {'peak_bw': 0, 'day_start': time.time()}
    while True:
        try:
            if int(time.time()) % 600 < 15:
                apply_multicore_rps()

            state = run_cycle(state)
            if time.time() - state.get('day_start', 0) >= 86400:
                log_event(
                    f"DAILY CONVERGENCE | Peak: {state['peak_bw']/1e6:.1f} Mbps | "
                    f"Avg RTT: {state.get('last_rtt', 0):.1f}ms | Loss: {state.get('last_loss', 0)*100:.3f}% | "
                    f"Active qlen: {state.get('last_qlen', 500)}"
                )
                state['day_start'] = time.time()
                state['peak_bw'] = 0
            time.sleep(10)
        except KeyboardInterrupt:
            break
        except Exception:
            time.sleep(10)

if __name__ == "__main__":
    main()
