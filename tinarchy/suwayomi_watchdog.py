#!/usr/bin/env python3
"""
Suwayomi Download Watchdog & Auto-Retry Service

Monitors the Suwayomi manga server download queue. When chapter downloads encounter
transient Cloudflare/CDN rate-limit errors (HTTP 503 / 500) and stall in ERROR state,
this service automatically applies a cooldown backoff, re-queues them to resume from
cached pages, and ensures hands-free 100% completion.
"""

import sys
import os
import time
import json
import base64
import argparse
import logging
import urllib.request
import urllib.error

CONF_PATH = "/var/lib/suwayomi/.local/share/Tachidesk/server.conf"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("suwayomi_watchdog")


def get_suwayomi_config():
    """Extracts endpoint and auth details from Suwayomi server.conf."""
    port = 4567
    subpath = "/manga"
    user = ""
    password = ""
    mode = "NONE"

    if os.path.exists(CONF_PATH):
        try:
            with open(CONF_PATH, "r", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if line.startswith("server.port"):
                        parts = line.split("=", 1)
                        if len(parts) == 2:
                            val = parts[1].split("#")[0].strip()
                            try:
                                port = int(val)
                            except ValueError:
                                pass
                    elif line.startswith("server.webUISubpath"):
                        parts = line.split("=", 1)
                        if len(parts) == 2:
                            val = parts[1].split("#")[0].strip().strip('"').strip("'")
                            subpath = val if val else ""
                    elif line.startswith("server.authUsername"):
                        parts = line.split("=", 1)
                        if len(parts) == 2:
                            user = parts[1].split("#")[0].strip().strip('"').strip("'")
                    elif line.startswith("server.authPassword"):
                        parts = line.split("=", 1)
                        if len(parts) == 2:
                            password = parts[1].split("#")[0].strip().strip('"').strip("'")
                    elif line.startswith("server.authMode"):
                        parts = line.split("=", 1)
                        if len(parts) == 2:
                            mode = parts[1].split("#")[0].strip().strip('"').strip("'")
        except Exception as e:
            logger.warning(f"Could not read {CONF_PATH}: {e}")

    # Fallback to defaults if empty
    if not user and os.environ.get("SUWAYOMI_USER"):
        user = os.environ.get("SUWAYOMI_USER")
    if not password and os.environ.get("SUWAYOMI_PASS"):
        password = os.environ.get("SUWAYOMI_PASS")

    # If subpath doesn't start with '/', normalize it
    if subpath and not subpath.startswith("/"):
        subpath = "/" + subpath
    if subpath.endswith("/"):
        subpath = subpath[:-1]

    gql_url = f"http://127.0.0.1:{port}{subpath}/api/graphql"

    auth_header = None
    if user and password:
        token = base64.b64encode(f"{user}:{password}".encode()).decode()
        auth_header = f"Basic {token}"

    return gql_url, auth_header


class SuwayomiClient:
    def __init__(self, gql_url=None, auth_header=None):
        if not gql_url:
            self.gql_url, self.auth_header = get_suwayomi_config()
        else:
            self.gql_url = gql_url
            self.auth_header = auth_header

    def query(self, gql_string, timeout=10):
        headers = {"Content-Type": "application/json"}
        if self.auth_header:
            headers["Authorization"] = self.auth_header

        data = json.dumps({"query": gql_string}).encode("utf-8")
        req = urllib.request.Request(self.gql_url, data=data, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status == 200:
                    return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", "ignore")
            logger.error(f"GraphQL HTTP Error {e.code}: {err_body}")
        except Exception as e:
            logger.error(f"GraphQL Query failed: {e}")
        return None

    def get_download_status(self):
        query = """
        {
            downloadStatus {
                state
                queue {
                    chapter {
                        id
                        name
                        manga {
                            title
                        }
                    }
                    state
                    progress
                    tries
                }
            }
        }
        """
        res = self.query(query)
        if res and "data" in res and "downloadStatus" in res["data"]:
            return res["data"]["downloadStatus"]
        return None

    def dequeue(self, chapter_id):
        mutation = f"""
        mutation {{
            dequeueChapterDownload(input: {{ id: {chapter_id} }}) {{
                clientMutationId
            }}
        }}
        """
        return self.query(mutation)

    def enqueue(self, chapter_id):
        mutation = f"""
        mutation {{
            enqueueChapterDownload(input: {{ id: {chapter_id} }}) {{
                clientMutationId
            }}
        }}
        """
        return self.query(mutation)

    def start_downloader(self):
        mutation = """
        mutation {
            startDownloader(input: {}) {
                clientMutationId
            }
        }
        """
        return self.query(mutation)


def run_watchdog(client, mode="once", cooldown=10, chapter_delay=3, poll_interval=20):
    logger.info(f"Suwayomi Watchdog started (Mode: {mode}, Cooldown: {cooldown}s, Pacing: {chapter_delay}s)")
    logger.info(f"Target Suwayomi GraphQL: {client.gql_url}")

    while True:
        status = client.get_download_status()
        if not status:
            logger.warning("Could not reach Suwayomi server. Retrying in 10s...")
            time.sleep(10)
            continue

        queue = status.get("queue", [])
        if not queue:
            if mode == "once":
                logger.info("Download queue is completely empty. All downloads finished!")
                return 0
            else:
                time.sleep(poll_interval)
                continue

        error_items = [x for x in queue if x.get("state") == "ERROR"]
        running_items = [x for x in queue if x.get("state") in ("DOWNLOADING", "QUEUED")]

        if not error_items and running_items:
            # Normal download in flight, check in shortly
            time.sleep(3)
            continue

        if error_items:
            logger.info(f"Found {len(error_items)} chapter(s) in ERROR state. Starting disciplined auto-retry...")

            for idx, item in enumerate(error_items, start=1):
                ch = item.get("chapter", {})
                ch_id = ch.get("id")
                ch_name = ch.get("name", "Unknown Chapter")
                manga_title = ch.get("manga", {}).get("title", "Unknown Manga")

                logger.info(f"[{idx}/{len(error_items)}] Resuming: '{manga_title}' - {ch_name} (ID: {ch_id})")

                # Dequeue and re-enqueue to reset the try counter
                client.dequeue(ch_id)
                time.sleep(0.5)
                client.enqueue(ch_id)
                client.start_downloader()

                # Monitor this chapter until it either finishes or errors out
                while True:
                    time.sleep(2)
                    cur_status = client.get_download_status()
                    if not cur_status:
                        time.sleep(3)
                        continue

                    cur_q = cur_status.get("queue", [])
                    active_item = next((x for x in cur_q if x.get("chapter", {}).get("id") == ch_id), None)

                    if not active_item:
                        logger.info(f"-> Completed '{ch_name}' successfully!")
                        # Pacing delay between chapters to keep CDN rate limits cool
                        time.sleep(chapter_delay)
                        break

                    state = active_item.get("state")
                    progress = active_item.get("progress", 0.0) * 100
                    tries = active_item.get("tries", 0)

                    if state == "ERROR":
                        logger.warning(
                            f"-> Hit CDN rate limit at {progress:.1f}% (tries={tries}). "
                            f"Cooling down {cooldown}s before resuming..."
                        )
                        time.sleep(cooldown)
                        client.dequeue(ch_id)
                        time.sleep(0.5)
                        client.enqueue(ch_id)
                        client.start_downloader()
                    else:
                        logger.debug(f"Progress for '{ch_name}': {progress:.1f}% ({state})")

        # After attempting to resolve error items, check state
        if mode == "once":
            final_status = client.get_download_status()
            final_q = final_status.get("queue", []) if final_status else []
            if not final_q:
                logger.info("All chapters in queue have finished successfully!")
                return 0
        else:
            time.sleep(poll_interval)


def main():
    parser = argparse.ArgumentParser(description="Suwayomi Download Watchdog & Auto-Retry")
    parser.add_argument("--once", action="store_true", help="Run until current queue is drained, then exit")
    parser.add_argument("--daemon", action="store_true", help="Run continuously in background")
    parser.add_argument("--cooldown", type=int, default=10, help="Cooldown in seconds after CDN 503 error (default: 10)")
    parser.add_argument("--delay", type=int, default=3, help="Delay in seconds between finished chapters (default: 3)")
    parser.add_argument("--interval", type=int, default=20, help="Poll interval in seconds for daemon mode (default: 20)")
    args = parser.parse_args()

    mode = "once" if args.once else "daemon"
    client = SuwayomiClient()
    sys.exit(run_watchdog(client, mode=mode, cooldown=args.cooldown, chapter_delay=args.delay, poll_interval=args.interval))


if __name__ == "__main__":
    main()
