# Troubleshooting

## Remote Web Access

If Home, Health, and TV Dashboard work on the local network and remotely, but
Scan Search or CSV Logs work only locally, test the browser page and its API
request separately.

Home, Health, and TV Dashboard all request
`/api/v1/dashboard/health`. Scan Search also requests `/api/v1/scanners`,
`/api/v1/scans/summary`, and `/api/v1/scans`. CSV Logs requests
`/api/v1/logs/daily-csv`. A layer-4 NAT or port-forward rule cannot distinguish
these URL paths, but an HTTP reverse proxy, web application firewall, or URL
allowlist can permit the dashboard endpoint while dropping the others.

From a remote client, replace `scanner.example.com` with the normal public host
and compare these requests:

```bash
curl --fail-with-body --max-time 20 https://scanner.example.com/search
curl --fail-with-body --max-time 20 https://scanner.example.com/logs
curl --fail-with-body --max-time 20 https://scanner.example.com/api/v1/dashboard/health
curl --fail-with-body --max-time 20 https://scanner.example.com/api/v1/scanners
curl --fail-with-body --max-time 20 https://scanner.example.com/api/v1/logs/daily-csv
```

At the scanner server, watch nginx while repeating the failing remote request:

```bash
sudo tail -f /var/log/nginx/access.log /var/log/nginx/error.log
sudo journalctl -u industrial-scanner-logger-api -f
```

- No nginx access-log entry means the request was stopped before it reached the
  app server. Check the firewall, reverse proxy, WAF, or URL allowlist.
- An nginx 502 or 504 means the request reached nginx but the API upstream did
  not answer successfully. Check the API service journal and local API request.
- A local success and remote timeout for the same API URL confirms the problem
  is on the remote HTTP path rather than in PostgreSQL search or CSV handling.

The browser pages stop waiting after 15 seconds and show a proxy/firewall hint.
The nginx template also serves `/search` directly, without relying on an
automatic directory redirect. After updating an installed app, run
`sudo update-services` to refresh the web files, then run
`sudo refresh-nginx-config` to render and activate the nginx route change.
