#!/usr/bin/env python3
"""
Axiom High-Performance Mass Minecraft Scanner Engine
Nuitka & Obfuscation Compatible Edition + Key System
"""

import argparse
import asyncio
import ipaddress
import json
import os
import signal
import socket
import ssl
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple, Any

try:
    import uvloop
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
except ImportError:
    pass

C_RESET = "\033[0m"
C_YELLOW = "\033[93m"
C_GREEN = "\033[92m"
C_CYAN = "\033[96m"
C_RED = "\033[91m"
C_BOLD = "\033[1m"
C_DIM = "\033[2m"

STATE_FILE = "scan_state.json"
CONFIG_FILE = "scanner_config.json"
KEY_SESSION_FILE = "key_session.json"
DEFAULT_PORTS = [25565, 19132, 25575, 25566, 25567, 25568, 25569, 25570]

# Thay thế URL này bằng đường dẫn Github Raw chứa danh sách key của bạn
GITHUB_KEY_RAW_URL = "https://raw.githubusercontent.com/script-roblox337/Key/refs/heads/main/key.json"

LCG_A = 1664525
LCG_C = 1013904223
LCG_M = 4294967296

SSL_CONTEXT = ssl.create_default_context()
SSL_CONTEXT.check_hostname = False
SSL_CONTEXT.verify_mode = ssl.CERT_NONE


def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')


# ==============================================================================
# KEY SYSTEM IMPLEMENTATION
# ==============================================================================

def fetch_keys_from_github(raw_url: str) -> Dict[str, Any]:
    """Tải danh sách key từ URL GitHub Raw."""
    req = urllib.request.Request(
        raw_url,
        headers={"User-Agent": "AxiomKeyValidator/1.0", "Cache-Control": "no-cache"}
    )
    try:
        with urllib.request.urlopen(req, timeout=10, context=SSL_CONTEXT) as response:
            if response.status == 200:
                data = response.read().decode("utf-8")
                return json.loads(data)
    except Exception as e:
        print(f"{C_RED}❌ Không thể kết nối tới Server Key trên GitHub: {e}{C_RESET}")
    return {}


def format_time_remaining(seconds: float) -> str:
    """Định dạng số giây còn lại thành ngày, giờ, phút, giây."""
    if seconds <= 0:
        return "Đã hết hạn"
    
    days = int(seconds // 86400)
    seconds %= 86400
    hours = int(seconds // 3600)
    seconds %= 3600
    minutes = int(seconds // 60)
    secs = int(seconds % 60)

    parts = []
    if days > 0:
        parts.append(f"{days} ngày")
    if hours > 0:
        parts.append(f"{hours} giờ")
    if minutes > 0:
        parts.append(f"{minutes} phút")
    parts.append(f"{secs} giây")

    return " ".join(parts)


def parse_expire_time(expire_str: str) -> Optional[datetime]:
    """Chuyển đổi chuỗi ISO / YYYY-MM-DD HH:MM:SS thành đối tượng datetime UTC."""
    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d"
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(expire_str, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def authenticate_user_key() -> str:
    """Xác thực Key người dùng và hiển thị thời gian còn lại."""
    saved_key = ""
    if os.path.exists(KEY_SESSION_FILE):
        try:
            with open(KEY_SESSION_FILE, "r", encoding="utf-8") as f:
                saved_key = json.load(f).get("key", "").strip()
        except Exception:
            pass

    print(f"{C_CYAN}🔄 Đang xác thực Key với Server GitHub...{C_RESET}")
    key_database = fetch_keys_from_github(GITHUB_KEY_RAW_URL)

    if not key_database or "keys" not in key_database:
        print(f"{C_RED}❌ Không thể tải danh sách Key. Vui lòng kiểm tra lại kết nối mạng hoặc URL GitHub.{C_RESET}")
        sys.exit(1)

    keys_dict = key_database.get("keys", {})

    # Thử kiểm tra key đã lưu trước đó
    if saved_key and saved_key in keys_dict:
        user_key = saved_key
    else:
        user_key = input(f"\n{C_BOLD}{C_YELLOW}🔑 Nhập Key truy cập của bạn: {C_RESET}").strip()

    while True:
        if user_key in keys_dict:
            expire_info = keys_dict[user_key].get("expire", "")
            expire_dt = parse_expire_time(expire_info)

            if expire_dt:
                now_utc = datetime.now(timezone.utc)
                remaining_seconds = (expire_dt - now_utc).total_seconds()

                if remaining_seconds > 0:
                    time_str = format_time_remaining(remaining_seconds)
                    print(f"\n{C_GREEN}✔ Key hợp lệ!{C_RESET}")
                    print(f"{C_BOLD}⏳ Thời gian sử dụng còn lại: {C_CYAN}{time_str}{C_RESET}")
                    
                    # Lưu session key
                    try:
                        with open(KEY_SESSION_FILE, "w", encoding="utf-8") as f:
                            json.dump({"key": user_key}, f)
                    except Exception:
                        pass

                    time.sleep(2)
                    return user_key
                else:
                    print(f"\n{C_RED}❌ Key [{user_key}] đã hết hạn vào lúc: {expire_info} UTC{C_RESET}")
            else:
                print(f"\n{C_RED}❌ Key có cấu hình thời gian hết hạn không hợp lệ trên Server.{C_RESET}")
        else:
            print(f"\n{C_RED}❌ Key không tồn tại hoặc không hợp lệ!{C_RESET}")

        user_key = input(f"\n{C_BOLD}{C_YELLOW}🔑 Vui lòng nhập lại Key khác: {C_RESET}").strip()


# ==============================================================================
# MINECRAFT PROTOCOL & SCANNER LOGIC
# ==============================================================================

class FastVarInt:
    @staticmethod
    def encode(val: int) -> bytes:
        out = bytearray()
        val = int(val)
        while True:
            b = val & 0x7F
            val >>= 7
            if val:
                out.append(b | 0x80)
            else:
                out.append(b)
                break
        return bytes(out)

    @staticmethod
    def read_from_buffer(buf: bytearray) -> Tuple[Optional[int], int]:
        val = 0
        shift = 0
        consumed = 0
        for byte in buf:
            consumed += 1
            val |= (int(byte) & 0x7F) << shift
            if not (int(byte) & 0x80):
                return val, consumed
            shift += 7
            if shift >= 35:
                raise ValueError("VarInt exceeds limit")
        return None, 0


class MinecraftProtocol:
    @staticmethod
    def build_handshake(host: str, port: int, protocol_version: int = 763) -> bytes:
        host_b = host.encode("utf-8")
        payload = bytearray()
        payload.extend(FastVarInt.encode(0x00))
        payload.extend(FastVarInt.encode(protocol_version))
        payload.extend(FastVarInt.encode(len(host_b)))
        payload.extend(host_b)
        payload.extend(int(port).to_bytes(2, byteorder="big"))
        payload.extend(FastVarInt.encode(1))

        packet = bytearray()
        packet.extend(FastVarInt.encode(len(payload)))
        packet.extend(payload)
        packet.extend(FastVarInt.encode(1))
        packet.extend(FastVarInt.encode(0x00))

        return bytes(packet)

    @staticmethod
    def parse_motd(description: Any) -> str:
        if isinstance(description, str):
            return description
        if isinstance(description, dict):
            text = description.get("text", "")
            if "extra" in description and isinstance(description["extra"], list):
                for part in description["extra"]:
                    if isinstance(part, dict):
                        text += part.get("text", "")
                    elif isinstance(part, str):
                        text += str(part)
            return text
        return ""


class RawSLPClientProtocol(asyncio.Protocol):
    def __init__(self, host: str, port: int, on_complete: asyncio.Future):
        self.host = host
        self.port = port
        self.on_complete = on_complete
        self.transport: Optional[asyncio.Transport] = None
        self.buffer = bytearray()

    def connection_made(self, transport: asyncio.Transport):
        self.transport = transport
        handshake_payload = MinecraftProtocol.build_handshake(self.host, self.port)
        self.transport.write(handshake_payload)

    def data_received(self, data: bytes):
        self.buffer.extend(data)
        try:
            pkt_len, consumed_len = FastVarInt.read_from_buffer(self.buffer)
            if pkt_len is None or len(self.buffer) < consumed_len + pkt_len:
                return

            payload_buf = self.buffer[consumed_len : consumed_len + pkt_len]
            pkt_id, consumed_id = FastVarInt.read_from_buffer(payload_buf)

            if pkt_id == 0x00:
                json_buf = payload_buf[consumed_id:]
                str_len, consumed_str = FastVarInt.read_from_buffer(json_buf)
                
                if str_len is not None and len(json_buf) >= consumed_str + str_len:
                    raw_json = json_buf[consumed_str : consumed_str + str_len]
                    parsed = json.loads(raw_json.decode("utf-8", errors="ignore"))
                    raw_motd = MinecraftProtocol.parse_motd(parsed.get("description", ""))

                    res = {
                        "ip": self.host,
                        "port": self.port,
                        "version": str(parsed.get("version", {}).get("name", "Unknown")),
                        "protocol": parsed.get("version", {}).get("protocol", -1),
                        "online_players": parsed.get("players", {}).get("online", 0),
                        "max_players": parsed.get("players", {}).get("max", 0),
                        "motd": raw_motd,
                        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    }
                    if not self.on_complete.done():
                        self.on_complete.set_result(res)
                    if self.transport:
                        self.transport.close()
                    return
        except Exception:
            pass

        if not self.on_complete.done():
            self.on_complete.set_result(None)
        if self.transport:
            self.transport.close()

    def connection_lost(self, exc):
        if not self.on_complete.done():
            self.on_complete.set_result(None)


async def ping_raw_socket(ip: str, port: int, timeout: float) -> Optional[Dict[str, Any]]:
    loop = asyncio.get_running_loop()
    on_complete = loop.create_future()

    try:
        transport, _ = await asyncio.wait_for(
            loop.create_connection(
                lambda: RawSLPClientProtocol(ip, port, on_complete),
                host=ip,
                port=port,
            ),
            timeout=timeout,
        )
    except Exception:
        return None

    try:
        result = await asyncio.wait_for(on_complete, timeout=timeout)
        return result
    except Exception:
        return None
    finally:
        if 'transport' in locals() and transport and not transport.is_closing():
            transport.close()


def sync_send_discord_webhook(webhook_url: str, res: Dict[str, Any]) -> float:
    if not webhook_url or not webhook_url.startswith("http"):
        return 0.0

    motd_display = res['motd'].strip() if res['motd'].strip() else "Không có thông tin MOTD"
    if len(motd_display) > 500:
        motd_display = motd_display[:500] + "..."

    embed = {
        "title": "🎮 Phát hiện Minecraft Server Mới!",
        "color": 3066993,
        "fields": [
            {"name": "🌐 Địa chỉ IP", "value": f"`{res['ip']}:{res['port']}`", "inline": True},
            {"name": "🏷️ Phiên bản", "value": f"`{res['version']}` (Protocol {res['protocol']})", "inline": True},
            {"name": "👥 Người chơi", "value": f"`{res['online_players']}/{res['max_players']}`", "inline": True},
            {"name": "📝 Mô tả MOTD", "value": f"```\n{motd_display}\n```", "inline": False}
        ],
        "footer": {"text": "Minecraft Scan Server"},
        "timestamp": datetime.utcnow().isoformat() + "Z"
    }

    payload = json.dumps({"embeds": [embed]}).encode("utf-8")
    req = urllib.request.Request(
        webhook_url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
        }
    )

    try:
        with urllib.request.urlopen(req, timeout=8, context=SSL_CONTEXT):
            return 0.0
    except urllib.error.HTTPError as e:
        if e.code == 429:
            try:
                err_data = json.loads(e.read().decode("utf-8"))
                return float(err_data.get("retry_after", 1.0))
            except Exception:
                return 2.0
        return 0.0
    except Exception:
        return 0.0


async def discord_webhook_worker(webhook_url: str, queue: asyncio.Queue):
    while True:
        res = await queue.get()
        if res is None:
            queue.task_done()
            break

        try:
            retry_after = await asyncio.to_thread(sync_send_discord_webhook, webhook_url, res)
            if retry_after > 0:
                await asyncio.sleep(retry_after)
                await asyncio.to_thread(sync_send_discord_webhook, webhook_url, res)
        except Exception:
            pass
        finally:
            queue.task_done()


def is_public_ipv4(ip_int: int) -> bool:
    b1 = (ip_int >> 24) & 0xFF
    b2 = (ip_int >> 16) & 0xFF

    if b1 in (0, 10, 127):
        return False
    if b1 == 172 and (16 <= b2 <= 31):
        return False
    if b1 == 192 and b2 == 168:
        return False
    if b1 == 100 and (64 <= b2 <= 127):
        return False
    if b1 >= 224:
        return False
    return True


def parse_ports(port_str: str) -> List[int]:
    ports = set()
    for item in port_str.split(","):
        item = item.strip()
        if not item:
            continue
        if "-" in item:
            try:
                s, e = map(int, item.split("-"))
                ports.update(range(max(1, s), min(65535, e + 1)))
            except ValueError:
                pass
        else:
            try:
                p = int(item)
                if 1 <= p <= 65535:
                    ports.add(p)
            except ValueError:
                pass
    return sorted(list(ports))


def load_config() -> Tuple[List[int], str]:
    ports = DEFAULT_PORTS.copy()
    webhook_url = ""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if "ports" in data and isinstance(data["ports"], list):
                    ports = sorted(list(set(data["ports"])))
                webhook_url = data.get("webhook_url", "")
        except Exception:
            pass
    return ports, webhook_url


def save_config(ports: List[int], webhook_url: str):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump({"ports": ports, "webhook_url": webhook_url}, f, indent=4)
    except Exception:
        pass


def interactive_port_selection(current_webhook: str) -> Tuple[List[int], str]:
    available_ports, webhook_url = load_config()
    if current_webhook:
        webhook_url = current_webhook

    selected_flags = [True] * len(available_ports)
    msg = ""

    while True:
        clear_screen()
        print(f"{C_BOLD}{C_CYAN}================ MENU CẤU HÌNH BỘ QUÉT ================{C_RESET}")
        print("Danh sách Port hiện tại:")
        
        total = len(available_ports)
        half = (total + 1) // 2

        for i in range(half):
            p1 = available_ports[i]
            s1 = selected_flags[i]
            st1 = f"{C_GREEN}[✓] CHỌN{C_RESET}" if s1 else f"{C_RED}[ ] BỎ  {C_RESET}"
            col1 = f"  {C_BOLD}{i+1:>2}.{C_RESET} Port {C_YELLOW}{p1:<5}{C_RESET} -> {st1}"

            if i + half < total:
                idx2 = i + half
                p2 = available_ports[idx2]
                s2 = selected_flags[idx2]
                st2 = f"{C_GREEN}[✓] CHỌN{C_RESET}" if s2 else f"{C_RED}[ ] BỎ  {C_RESET}"
                col2 = f"  {C_BOLD}{idx2+1:>2}.{C_RESET} Port {C_YELLOW}{p2:<5}{C_RESET} -> {st2}"
                print(f"{col1:<42} {col2}")
            else:
                print(col1)

        webhook_status = f"{C_GREEN}{webhook_url[:45]}...{C_RESET}" if webhook_url else f"{C_RED}Chưa cấu hình{C_RESET}"
        print(f"\n{C_BOLD}Discord Webhook:{C_RESET} {webhook_status}")

        print(f"\n{C_BOLD}Thao tác khả dụng:{C_RESET}")
        print(f"  {C_GREEN}[S]{C_RESET} : Bắt đầu quét")
        print(f"  {C_CYAN}[W]{C_RESET} : Cập nhật URL Discord Webhook")
        print(f"  {C_CYAN}[A]{C_RESET} : Chọn tất cả / Bỏ chọn tất cả Port")
        print(f"  {C_CYAN}[+]{C_RESET} : Thêm Port/Dải Port mới vào danh sách")
        print(f"  {C_RED}[-]{C_RESET} : Chọn Port cần xóa khỏi danh sách")
        print(f"  {C_CYAN}[R]{C_RESET} : Khôi phục danh sách Port mặc định")
        print(f"  [Số] : Bật/Tắt Port theo số STT (VD: 1 hoặc 1,3,4)")

        if msg:
            print(f"\n{msg}")
            msg = ""

        user_input = input(f"\n{C_BOLD}Nhập lựa chọn của bạn: {C_RESET}").strip().upper()

        if user_input == "S":
            final_ports = [p for p, active in zip(available_ports, selected_flags) if active]
            if not final_ports:
                msg = f"{C_RED}❌ Bạn chưa chọn port nào! Vui lòng chọn ít nhất 1 port.{C_RESET}"
                continue
            save_config(available_ports, webhook_url)
            clear_screen()
            return final_ports, webhook_url

        elif user_input == "W":
            new_wh = input(f"\nNhập URL Discord Webhook (Để trống để hủy bỏ webhook): ").strip()
            webhook_url = new_wh
            save_config(available_ports, webhook_url)
            msg = f"{C_GREEN}✔ Đã cập nhật cấu hình Webhook!{C_RESET}"

        elif user_input == "A":
            all_active = all(selected_flags)
            selected_flags = [not all_active] * len(available_ports)

        elif user_input == "+":
            raw_add = input("\nNhập Port/Dải Port muốn thêm (VD: 25571 hoặc 25580-25585): ").strip()
            new_ports = parse_ports(raw_add)
            if new_ports:
                for np in new_ports:
                    if np not in available_ports:
                        available_ports.append(np)
                        selected_flags.append(True)
                combined = sorted(zip(available_ports, selected_flags), key=lambda x: x[0])
                available_ports = [p for p, _ in combined]
                selected_flags = [s for _, s in combined]
                save_config(available_ports, webhook_url)
                msg = f"{C_GREEN}✔ Đã thêm port thành công!{C_RESET}"
            else:
                msg = f"{C_RED}❌ Cú pháp Port không hợp lệ!{C_RESET}"

        elif user_input == "-":
            if not available_ports:
                msg = f"{C_YELLOW}⚠ Danh sách port đang trống!{C_RESET}"
                continue

            clear_screen()
            print(f"{C_BOLD}{C_RED}================ DANH SÁCH PORT ĐỂ XÓA ================{C_RESET}")
            tot_del = len(available_ports)
            half_del = (tot_del + 1) // 2

            for i in range(half_del):
                p1 = available_ports[i]
                col1 = f"  {C_BOLD}{i+1:>2}.{C_RESET} Port {C_YELLOW}{p1}{C_RESET}"

                if i + half_del < tot_del:
                    idx2 = i + half_del
                    p2 = available_ports[idx2]
                    col2 = f"  {C_BOLD}{idx2+1:>2}.{C_RESET} Port {C_YELLOW}{p2}{C_RESET}"
                    print(f"{col1:<30} {col2}")
                else:
                    print(col1)

            del_input = input(f"\n{C_BOLD}Nhập STT hoặc Port muốn xóa: {C_RESET}").strip()
            if not del_input:
                continue

            ports_to_remove = set()
            try:
                parts = [x.strip() for x in del_input.split(",") if x.strip()]
                is_stt = True
                indices = []
                for p in parts:
                    if p.isdigit():
                        val = int(p)
                        if 1 <= val <= len(available_ports):
                            indices.append(val - 1)
                        else:
                            is_stt = False
                            break
                    else:
                        is_stt = False
                        break

                if is_stt and indices:
                    for idx in indices:
                        ports_to_remove.add(available_ports[idx])
            except Exception:
                pass

            if not ports_to_remove:
                del_ports = parse_ports(del_input)
                for dp in del_ports:
                    if dp in available_ports:
                        ports_to_remove.add(dp)

            if ports_to_remove:
                new_avail = []
                new_flags = []
                for p, s in zip(available_ports, selected_flags):
                    if p in ports_to_remove:
                        continue
                    new_avail.append(p)
                    new_flags.append(s)

                available_ports = new_avail
                selected_flags = new_flags
                save_config(available_ports, webhook_url)
                msg = f"{C_GREEN}✔ Đã xóa {len(ports_to_remove)} port khỏi danh sách!{C_RESET}"
            else:
                msg = f"{C_RED}❌ Lựa chọn không hợp lệ!{C_RESET}"

        elif user_input == "R":
            available_ports = DEFAULT_PORTS.copy()
            selected_flags = [True] * len(available_ports)
            save_config(available_ports, webhook_url)
            msg = f"{C_GREEN}✔ Đã khôi phục danh sách mặc định.{C_RESET}"

        else:
            try:
                indices = [int(x.strip()) - 1 for x in user_input.split(",") if x.strip().isdigit()]
                valid_toggle = False
                for idx in indices:
                    if 0 <= idx < len(selected_flags):
                        selected_flags[idx] = not selected_flags[idx]
                        valid_toggle = True
                if not valid_toggle:
                    msg = f"{C_RED}❌ Số thứ tự không hợp lệ!{C_RESET}"
            except Exception:
                msg = f"{C_RED}❌ Lựa chọn không hợp lệ.{C_RESET}"


def load_checkpoint() -> Tuple[int, int]:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                d = json.load(f)
                state = d.get("lcg_state", 1)
                return (state | 1), d.get("scanned_ips", 0)
        except Exception:
            pass
    init_seed = (int(time.time()) % LCG_M) | 1
    return init_seed, 0


def save_checkpoint(lcg_state: int, scanned_ips: int):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({"lcg_state": lcg_state, "scanned_ips": scanned_ips}, f)
    except Exception:
        pass


def write_txt_result(res: Dict[str, Any], txt_path: str):
    txt_entry = (
        f" Server IP : {res['ip']}:{res['port']}\n"
        f" Phiên bản : {res['version']} (Protocol: {res['protocol']})\n"
        f" Người chơi: {res['online_players']}/{res['max_players']}\n"
        f" Mô tả MOTD: {res['motd']}\n"
        f" Thời gian : {res['time']}\n"
        f"--------------------------------------------------\n"
    )
    with open(txt_path, "a", encoding="utf-8") as f:
        f.write(txt_entry)


async def worker_node(
    queue: asyncio.Queue,
    semaphore: asyncio.Semaphore,
    timeout: float,
    txt_path: str,
    webhook_queue: Optional[asyncio.Queue],
    stats: Dict[str, Any],
):
    while True:
        target = await queue.get()
        if target is None:
            queue.task_done()
            break

        ip, port = target
        try:
            async with semaphore:
                stats["checks"] += 1
                
                if stats["checks"] % 1000 == 0:
                    elapsed = max(1.0, time.time() - stats["start_time"])
                    pps = stats["checks"] / elapsed
                    sys.stdout.write(
                        f"\r\033[K{C_YELLOW}⚡ Conn: {stats['checks']:,} | "
                        f"IP: {stats['ips']:,} | F: {stats['found']} | "
                        f"{pps:.0f} r/s{C_RESET}"
                    )
                    sys.stdout.flush()

                res = await ping_raw_socket(ip, port, timeout)
                if res:
                    stats["found"] += 1
                    
                    motd_single_line = res['motd'].replace('\n', ' ')
                    sys.stdout.write(
                        f"\r\033[K{C_GREEN}✔ [{res['ip']}:{res['port']}]{C_RESET} | "
                        f"{C_CYAN}Ver: {res['version']}{C_RESET} | "
                        f"{C_YELLOW}Online: {res['online_players']}/{res['max_players']}{C_RESET} | "
                        f"{C_DIM}{motd_single_line[:35]}{C_RESET}\n"
                    )
                    sys.stdout.flush()

                    write_txt_result(res, txt_path)

                    if webhook_queue is not None:
                        await webhook_queue.put(res)
        finally:
            queue.task_done()


async def target_generator(
    queue: asyncio.Queue,
    ports: List[int],
    total_ips_to_scan: int,
    initial_lcg: int,
    base_ip_count: int,
    stats: Dict[str, Any],
):
    state = initial_lcg
    scanned = 0

    try:
        while scanned < total_ips_to_scan:
            state = (LCG_A * state + LCG_C) % LCG_M
            if is_public_ipv4(state):
                ip_str = str(ipaddress.IPv4Address(state))
                for p in ports:
                    await queue.put((ip_str, p))

                scanned += 1
                stats["ips"] = base_ip_count + scanned

                if scanned % 2000 == 0:
                    save_checkpoint(state, stats["ips"])
    except asyncio.CancelledError:
        save_checkpoint(state, base_ip_count + scanned)
        raise

    save_checkpoint(state, base_ip_count + scanned)


async def main():
    parser = argparse.ArgumentParser(description="Axiom High-Throughput Global Scanner")
    parser.add_argument("--ports", type=str, default="", help="Chuỗi port cách nhau bởi dấu phẩy")
    parser.add_argument("--webhook", type=str, default="", help="URL Discord Webhook")
    parser.add_argument("--concurrency", type=int, default=2000, help="Số socket kết nối đồng thời")
    parser.add_argument("--timeout", type=float, default=2.5, help="Thời gian chờ socket (giây)")
    parser.add_argument("--output", type=str, default="minecraft_results.txt", help="File lưu kết quả")
    parser.add_argument("--ip-count", type=int, default=999999999999, help="Tổng số IP muốn quét")
    parser.add_argument("--reset", action="store_true", help="Xóa tiến trình đã lưu")

    args = parser.parse_args()

    # Bước 1: Gọi Key System xác thực trước khi chạy bất kỳ logic nào
    authenticate_user_key()

    if args.reset and os.path.exists(STATE_FILE):
        os.remove(STATE_FILE)

    config_ports, config_webhook = load_config()
    webhook_url = args.webhook if args.webhook else config_webhook

    if args.ports:
        ports = parse_ports(args.ports)
    else:
        ports, webhook_url = interactive_port_selection(webhook_url)

    current_lcg, scanned_ips = load_checkpoint()

    print(f"{C_BOLD}{C_CYAN}===================================================={C_RESET}")
    print(f"{C_BOLD}{C_GREEN}AXIOM HIGH-THROUGHPUT MINECRAFT SCANNER ENGINE{C_RESET}")
    print(f"Target Ports       : {len(ports)} ports -> {ports}")
    print(f"Concurrency        : {args.concurrency} sockets")
    print(f"Timeout            : {args.timeout}s")
    print(f"Discord Webhook    : {'Đã bật' if webhook_url else 'Tắt'}")
    print(f"Resumed LCG State  : {current_lcg}")
    print(f"Already Evaluated  : {scanned_ips:,} IPs")
    print(f"{C_BOLD}{C_CYAN}===================================================={C_RESET}\n")

    queue = asyncio.Queue(maxsize=args.concurrency * 2)
    semaphore = asyncio.Semaphore(args.concurrency)
    stats = {"checks": 0, "ips": scanned_ips, "found": 0, "start_time": time.time()}

    webhook_queue = None
    webhook_task = None
    if webhook_url:
        webhook_queue = asyncio.Queue()
        webhook_task = asyncio.create_task(discord_webhook_worker(webhook_url, webhook_queue))

    workers = [
        asyncio.create_task(worker_node(queue, semaphore, args.timeout, args.output, webhook_queue, stats))
        for _ in range(args.concurrency)
    ]

    producer_task = asyncio.create_task(
        target_generator(queue, ports, args.ip_count, current_lcg, scanned_ips, stats)
    )

    loop = asyncio.get_running_loop()

    def handle_interrupt():
        sys.stdout.write(f"\n{C_YELLOW}[!] Interrupted. Saving LCG progress state...{C_RESET}\n")
        producer_task.cancel()
        for w in workers:
            w.cancel()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, handle_interrupt)
        except NotImplementedError:
            pass

    try:
        await producer_task
        await queue.join()
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        producer_task.cancel()
        for w in workers:
            w.cancel()
        if webhook_queue:
            await webhook_queue.put(None)
            if webhook_task:
                await webhook_task
        await asyncio.gather(producer_task, *workers, return_exceptions=True)
        print(f"\n{C_GREEN}✔ Đã lưu kết quả thành công vào file '{args.output}'!{C_RESET}")


if __name__ == "__main__":
    clear_screen()
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
