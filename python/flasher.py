import tkinter as tk
from tkinter import filedialog, messagebox
import os
import serial
import serial.tools.list_ports
import threading
import zlib, struct
import time

# Protocol constants
SYNC = b'\x55\xAA'
CMD_ERASE = 0x01
CMD_WRITE = 0x02
CMD_RUN   = 0x04
APP_BASE  = 0x08010000

ser = None
stop_reading = False

def pkt(cmd, addr, payload=b''):
    body = struct.pack('<B H I', cmd, len(payload), addr) + payload
    crc  = zlib.crc32(body) & 0xFFFFFFFF
    return SYNC + body + struct.pack('<I', crc)

def select_file():
    file_path = filedialog.askopenfilename(
        title="Select BIN file",
        filetypes=[("BIN files", "*.bin"), ("All files", "*.*")]
    )
    if file_path:
        entry_file.delete(0, tk.END)
        entry_file.insert(0, file_path)

def refresh_ports():
    ports = serial.tools.list_ports.comports()
    port_list = [port.device for port in ports]
    port_var.set("")  # clear selection
    menu_ports['menu'].delete(0, 'end')
    for p in port_list:
        menu_ports['menu'].add_command(label=p, command=tk._setit(port_var, p))
    if port_list:
        port_var.set(port_list[0])  # auto-select first port

def send_binary():
    global ser
    port = port_var.get()
    file_path = entry_file.get()
    if not port:
        messagebox.showerror("Error", "Please select a USB port")
        return
    if not os.path.isfile(file_path):
        messagebox.showerror("Error", "Please select a valid binary file")
        return
    
    try:
        ser = serial.Serial(port, baudrate=115200, timeout=1)
        #start_reading()

        with open(file_path, "rb") as f:
            data = f.read()

        # align length to 8
        pad = (8 - (len(data) % 8)) % 8
        data += b'\xFF' * pad

        # -------- ERASE FLASH --------
        erase_size = len(data)

        # payload = erase size (uint32)
        erase_payload = struct.pack('<I', erase_size)

        erase_pkt = pkt(CMD_ERASE, APP_BASE, erase_payload)

        print("\n=== ERASE Packet ===")
        print(f"Erase addr: {hex(APP_BASE)}")
        print(f"Erase size: {erase_size} bytes")
        print(erase_pkt.hex(" "))

        ser.write(erase_pkt)

        ack = ser.read(2)  # expect 'A', status
        print(f"ERASE ACK: {ack.hex() if ack else 'None'}")

        if len(ack) != 2 or ack[0] != ord('A') or ack[1] != 0:
            raise RuntimeError("Flash erase failed")

        time.sleep(1)

        addr = APP_BASE
        CHUNK_SIZE = 512
        total_chunks = (len(data) + CHUNK_SIZE - 1) // CHUNK_SIZE

        for off in range(0, len(data), CHUNK_SIZE):
            chunk = data[off:off+CHUNK_SIZE]
            packet = pkt(CMD_WRITE, addr + off, chunk)

            # Print logs to terminal
            print(f"\n=== Chunk {off//CHUNK_SIZE+1}/{total_chunks} ===")
            print(f"Addr: {hex(addr+off)}")
            print(f"Payload length: {len(chunk)}")
            print(f"Packet (first 32 bytes): {packet[:512].hex(' ')} ...")

            ser.write(packet)
            ack = ser.read(2)  # expect 'A', status
            print(f"ACK: {ack.hex() if ack else 'None'}")

            if len(ack) != 2 or ack[0] != ord('A') or ack[1] != 0:
                raise RuntimeError(f'Write failed at {hex(addr+off)}: {ack}')
            time.sleep(0.5)

        # jump
        run_pkt = pkt(CMD_RUN, APP_BASE)
        print("\n=== RUN Packet ===")
        print(run_pkt.hex(" "))
        ser.write(run_pkt)

        print("Sent RUN command")

        messagebox.showinfo("Success", "Binary file sent in chunks and RUN command issued.")
    except Exception as e:
        messagebox.showerror("Error", f"Failed to send binary:\n{e}")


def send_data():
    global ser
    port = port_var.get()
    data = console_entry.get("1.0", tk.END).strip()
    if not port:
        messagebox.showerror("Error", "Please select a USB port")
        return
    if not data:
        messagebox.showerror("Error", "Please enter some data to send")
        return
    
    try:
        if ser is None or not ser.is_open:
            ser = serial.Serial(port, baudrate=115200, timeout=1)
            start_reading()
        ser.write(data.encode('utf-8'))
        messagebox.showinfo("Success", f"Data sent:\n{data}")
    except Exception as e:
        messagebox.showerror("Error", f"Failed to send data:\n{e}")

def start_reading():
    global stop_reading
    stop_reading = False
    threading.Thread(target=read_data, daemon=True).start()

def read_data():
    global ser, stop_reading
    while not stop_reading and ser and ser.is_open:
        try:
            # read whatever is available
            data = ser.read(64)  # read up to 64 bytes at a time
            if data:
                # convert to hex string
                hex_str = data.hex(" ")
                console_output.insert(tk.END, hex_str + "\n")
                console_output.see(tk.END)
                # also print to terminal for debugging
                print(f"RX: {hex_str}")
        except Exception:
            break

def on_close():
    global stop_reading, ser
    stop_reading = True
    if ser and ser.is_open:
        ser.close()
    root.destroy()

# Tkinter UI
root = tk.Tk()
root.title("USB Binary Flasher & Debug Console")

# File selection
tk.Label(root, text="Select BIN File:").pack(pady=5)
frame_file = tk.Frame(root)
frame_file.pack(pady=5)
entry_file = tk.Entry(frame_file, width=50)
entry_file.pack(side=tk.LEFT, padx=5)
tk.Button(frame_file, text="Browse", command=select_file).pack(side=tk.LEFT)

# USB port selection
tk.Label(root, text="Select USB Port:").pack(pady=5)
port_var = tk.StringVar(root)
menu_ports = tk.OptionMenu(root, port_var, "")
menu_ports.pack(pady=5)
tk.Button(root, text="Refresh Ports", command=refresh_ports).pack(pady=5)

# Console box for sending data
tk.Label(root, text="Debug Console (send data):").pack(pady=5)
console_entry = tk.Text(root, height=5, width=60)
console_entry.pack(pady=5)
tk.Button(root, text="Send", command=send_data).pack(pady=5)

# Console box for receiving data
tk.Label(root, text="Received Data:").pack(pady=5)
console_output = tk.Text(root, height=10, width=60, state=tk.NORMAL)
console_output.pack(pady=5)

# Binary send button
tk.Button(root, text="Send Binary (chunked)", command=send_binary).pack(pady=10)

# Load ports at startup
refresh_ports()

root.protocol("WM_DELETE_WINDOW", on_close)
root.mainloop()
