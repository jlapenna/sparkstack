# Maintenance Refactor Plan

1. Reconcile README.md to reflect ground truth (Docker is rootless binary, Caddy is Docker, etc.).
1. Delete service_plan.md entirely once reconciled.
1. Delete bin/pike-update and disable its timers.
   Configure unattended-upgrades natively for host OS updates.
1. Rely on Watchtower for container updates.
1. Create bin/sync-identity strictly for Ansible Authelia/SSH sync (no host apt tasks).
