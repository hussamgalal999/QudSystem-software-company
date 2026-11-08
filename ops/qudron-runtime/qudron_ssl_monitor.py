#!/usr/bin/env python3
"""Qudron Live SSL & Health Monitor.
Extracted and adapted autonomously from GitHub: ak545/ssl-host-expiration-checker
For QudSystem.Ltd infrastructure monitoring.
"""
from __future__ import annotations
import sys
import socket
import ssl
import time
import urllib.request
from datetime import datetime, timezone

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

TARGET_URL = "https://qud-system-software-company-it-solutions-web-application.vercel.app"
TARGET_HOST = "qud-system-software-company-it-solutions-web-application.vercel.app"

def check_ssl_and_health():
    print(f"[فحص حي]: جاري التحقق من أمان وصحة: {TARGET_HOST}")
    
    # 1. فحص زمن الاستجابة و HTTP Status
    start = time.time()
    try:
        req = urllib.request.Request(TARGET_URL, headers={"User-Agent": "Qudron-Monitor/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            latency_ms = round((time.time() - start) * 1000, 2)
            status_code = resp.getcode()
            print(f"  [HTTP Status]: {status_code} OK")
            print(f"  [Latency]: {latency_ms} ms")
    except urllib.error.HTTPError as e:
        print(f"  [HTTP Status]: {e.code} (Vercel deployment route)")
    except Exception as e:
        print(f"  [HTTP Error]: {e}")

    # 2. استخراج شهادة الـ SSL وفحص صلاحيتها
    try:
        context = ssl.create_default_context()
        with socket.create_connection((TARGET_HOST, 443), timeout=10) as sock:
            with context.wrap_socket(sock, server_hostname=TARGET_HOST) as ssock:
                cert = ssock.getpeercert()
                
                # تواريخ الشهادة
                not_after_str = cert["notAfter"]
                expiry_date = datetime.strptime(not_after_str, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
                now = datetime.now(timezone.utc)
                days_left = (expiry_date - now).days
                
                issuer = dict(x[0] for x in cert["issuer"])
                common_name = issuer.get("commonName", "Unknown CA")
                organization = issuer.get("organizationName", common_name)
                
                print(f"  [SSL Status]: شهادة الأمان صالحة ومؤمنة")
                print(f"  [Issuer]: {organization} ({common_name})")
                print(f"  [Expiry Date]: {expiry_date.strftime('%Y-%m-%d %H:%M:%S UTC')}")
                print(f"  [Days Left]: {days_left} يوم")
                
                if days_left > 15:
                    print(f"  [Security Rating]: ممتاز (الشهادة في فترة أمان كافية)")
                else:
                    print(f"  [Warning]: الشهادة تقترب من موعد الانتهاء!")
    except Exception as e:
        print(f"  [SSL Error]: {e}")

if __name__ == "__main__":
    check_ssl_and_health()
