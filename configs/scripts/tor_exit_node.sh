#!/bin/bash
ACTION=$1

# Clean up any existing rules first to remain idempotent
iptables -t nat -D PREROUTING -i tailscale0 -j TOR_EXIT 2>/dev/null
iptables -t nat -F TOR_EXIT 2>/dev/null
iptables -t nat -X TOR_EXIT 2>/dev/null

iptables -D FORWARD -i tailscale0 -j TOR_EXIT_FILTER 2>/dev/null
iptables -F TOR_EXIT_FILTER 2>/dev/null
iptables -X TOR_EXIT_FILTER 2>/dev/null

ip6tables -D FORWARD -i tailscale0 -j TOR_EXIT_FILTER_V6 2>/dev/null
ip6tables -F TOR_EXIT_FILTER_V6 2>/dev/null
ip6tables -X TOR_EXIT_FILTER_V6 2>/dev/null

if [ "$ACTION" = "start" ]; then
    # Ensure Tor service is running
    systemctl start tor

    # Create NAT redirection chain for Tor
    iptables -t nat -N TOR_EXIT
    iptables -t nat -A TOR_EXIT -p udp --dport 53 -j REDIRECT --to-ports 5353
    iptables -t nat -A TOR_EXIT -p tcp --dport 53 -j REDIRECT --to-ports 5353
    iptables -t nat -A TOR_EXIT -d 10.0.0.0/8 -j RETURN
    iptables -t nat -A TOR_EXIT -d 172.16.0.0/12 -j RETURN
    iptables -t nat -A TOR_EXIT -d 192.168.0.0/16 -j RETURN
    iptables -t nat -A TOR_EXIT -d 100.64.0.0/10 -j RETURN
    iptables -t nat -A TOR_EXIT -p tcp -j REDIRECT --to-ports 9040
    iptables -t nat -I PREROUTING -i tailscale0 -j TOR_EXIT

    # Filter non-TCP / non-DNS traffic to prevent IP leaks
    iptables -N TOR_EXIT_FILTER
    iptables -A TOR_EXIT_FILTER -d 10.0.0.0/8 -j RETURN
    iptables -A TOR_EXIT_FILTER -d 172.16.0.0/12 -j RETURN
    iptables -A TOR_EXIT_FILTER -d 192.168.0.0/16 -j RETURN
    iptables -A TOR_EXIT_FILTER -d 100.64.0.0/10 -j RETURN
    iptables -A TOR_EXIT_FILTER -p tcp -j ACCEPT
    iptables -A TOR_EXIT_FILTER -p udp --dport 53 -j ACCEPT
    iptables -A TOR_EXIT_FILTER -j REJECT
    iptables -I FORWARD -i tailscale0 -j TOR_EXIT_FILTER
    
    # Prevent IPv6 leaks
    ip6tables -N TOR_EXIT_FILTER_V6
    ip6tables -A TOR_EXIT_FILTER_V6 -d fd7a:115c:a1e0::/48 -j RETURN
    ip6tables -A TOR_EXIT_FILTER_V6 -j REJECT
    ip6tables -I FORWARD -i tailscale0 -j TOR_EXIT_FILTER_V6
fi
