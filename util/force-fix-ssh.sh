#!/bin/bash

LOG_FILE="/home/jlapenna/p/sparkstack/ssh-watchdog.log"
echo "Starting SSH force-fix watchdog... Logging to $LOG_FILE" | tee -a "$LOG_FILE"

while true; do
    echo "--- $(date) ---" >> "$LOG_FILE"

    # Log Memory and CPU status
    echo "[Metrics] RAM and Load:" >> "$LOG_FILE"
    free -h >> "$LOG_FILE"
    uptime >> "$LOG_FILE"
    
    # Log any recent OOM events from dmesg
    echo "[OOM Check] Recent Out of Memory events:" >> "$LOG_FILE"
    dmesg | grep -i oom | tail -n 5 >> "$LOG_FILE"

    # Check and insert for port 222
    if ! iptables -C INPUT -p tcp --dport 222 -j ACCEPT 2>/dev/null; then
        iptables -I INPUT 1 -p tcp --dport 222 -j ACCEPT
        echo "$(date): Re-inserted SSH rule for port 222" | tee -a "$LOG_FILE"
    else
        echo "Port 222 rule is PRESENT" >> "$LOG_FILE"
    fi

    # Check and insert for port 8234
    if ! iptables -C INPUT -p tcp --dport 8234 -j ACCEPT 2>/dev/null; then
        iptables -I INPUT 1 -p tcp --dport 8234 -j ACCEPT
        echo "$(date): Re-inserted SSH rule for port 8234" | tee -a "$LOG_FILE"
    else
        echo "Port 8234 rule is PRESENT" >> "$LOG_FILE"
    fi

    # Optional: also add to DOCKER-USER just in case it's being forwarded
    if iptables -L DOCKER-USER >/dev/null 2>&1; then
        if ! iptables -C DOCKER-USER -p tcp --dport 222 -j ACCEPT 2>/dev/null; then
            iptables -I DOCKER-USER 1 -p tcp --dport 222 -j ACCEPT
            echo "$(date): Re-inserted SSH rule for port 222 (DOCKER-USER)" | tee -a "$LOG_FILE"
        fi
        if ! iptables -C DOCKER-USER -p tcp --dport 8234 -j ACCEPT 2>/dev/null; then
            iptables -I DOCKER-USER 1 -p tcp --dport 8234 -j ACCEPT
            echo "$(date): Re-inserted SSH rule for port 8234 (DOCKER-USER)" | tee -a "$LOG_FILE"
        fi
    fi

    echo "-------------------" >> "$LOG_FILE"
    sleep 2
done
