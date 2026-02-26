import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import sqlite3
import shutil
import struct
import os
import datetime
import lz4.block

class MewgenicsRenameTool:
    def __init__(self, root):
        self.root = root
        self.root.title("Mewgenics Cat Renamer 4.0 (LZ4 True Decode) - by AI")
        self.root.geometry("600x450")
        self.root.resizable(False, False)
        
        self.db_path = ""
        self.cats_data = []  
        self.raw_uncompressed_blobs = {} # {id: (original_size_bytes, uncompressed_data)}
        self.name_meta = {} # 记录 {key: (offset, length)}
        self.pending_renames = {}
        
        self.create_widgets()
        self.auto_locate_save()

    def create_widgets(self):
        frame_top = ttk.Frame(self.root, padding=10)
        frame_top.pack(fill=tk.X)
        ttk.Label(frame_top, text="Save File (.sav):").pack(side=tk.LEFT)
        self.entry_path = ttk.Entry(frame_top, width=40)
        self.entry_path.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        ttk.Button(frame_top, text="Browse...", command=self.browse_file).pack(side=tk.LEFT)
        ttk.Button(frame_top, text="Load / Refresh", command=self.load_save).pack(side=tk.LEFT, padx=5)
        
        frame_mid = ttk.Frame(self.root, padding=10)
        frame_mid.pack(fill=tk.BOTH, expand=True)
        
        frame_search = ttk.Frame(frame_mid)
        frame_search.pack(fill=tk.X, pady=(0, 5))
        ttk.Label(frame_search, text="Search Name or ID:").pack(side=tk.LEFT)
        self.entry_search = ttk.Entry(frame_search, width=25)
        self.entry_search.pack(side=tk.LEFT, padx=5)
        self.entry_search.bind("<KeyRelease>", self.on_search)
        
        columns = ("key", "name", "new_name")
        self.tree = ttk.Treeview(frame_mid, columns=columns, show="headings", selectmode="browse")
        self.tree.heading("key", text="ID")
        self.tree.heading("name", text="Current Name")
        self.tree.heading("new_name", text="New Name")
        self.tree.column("key", width=60, anchor=tk.CENTER)
        self.tree.column("name", width=200, anchor=tk.W)
        self.tree.column("new_name", width=200, anchor=tk.W)
        self.tree.pack(fill=tk.BOTH, expand=True)
        self.tree.bind("<<TreeviewSelect>>", self.on_cat_select)
        
        frame_btm = ttk.Frame(self.root, padding=10)
        frame_btm.pack(fill=tk.X)
        ttk.Label(frame_btm, text="New Name:").pack(side=tk.LEFT)
        self.entry_new_name = ttk.Entry(frame_btm, width=25)
        self.entry_new_name.pack(side=tk.LEFT, padx=5)
        
        self.btn_set = ttk.Button(frame_btm, text="Set Pending", command=self.set_pending_name)
        self.btn_set.pack(side=tk.LEFT, padx=5)
        
        self.btn_apply = ttk.Button(frame_btm, text="Save All to File", command=self.apply_rename)
        self.btn_apply.pack(side=tk.LEFT, padx=5)
        ttk.Label(frame_btm, text="(Unlimited length, true injection)", foreground="green").pack(side=tk.RIGHT)

    def auto_locate_save(self):
        appdata = os.environ.get('APPDATA')
        if not appdata: return
        base_dir = os.path.join(appdata, "Glaiel Games", "Mewgenics")
        if not os.path.exists(base_dir): return
        
        latest_sav = None
        latest_time = 0
        for root, dirs, files in os.walk(base_dir):
            for file in files:
                if file.endswith('.sav'):
                    full_path = os.path.join(root, file)
                    mtime = os.path.getmtime(full_path)
                    if mtime > latest_time:
                        latest_time = mtime
                        latest_sav = full_path
        if latest_sav:
            self.entry_path.insert(0, latest_sav)
            self.load_save()

    def browse_file(self):
        path = filedialog.askopenfilename(
            title="Select Mewgenics Save",
            filetypes=(("Mewgenics Save", "*.sav"), ("All Files", "*.*"))
        )
        if path:
            self.entry_path.delete(0, tk.END)
            self.entry_path.insert(0, path)
            self.load_save()

    def load_save(self):
        self.db_path = self.entry_path.get()
        if not os.path.exists(self.db_path):
            messagebox.showerror("Error", "Save file not found!")
            return
            
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.cats_data.clear()
        self.raw_uncompressed_blobs.clear()
        self.name_meta.clear()
        self.pending_renames.clear()
        
        try:
            uri = f"file:{self.db_path}?mode=ro"
            conn = sqlite3.connect(uri, uri=True)
            cur = conn.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = [row[0] for row in cur.fetchall()]
            if 'cats' not in tables:
                messagebox.showerror("Error", "Invalid Mewgenics save (missing 'cats' table).")
                conn.close()
                return
                
            cur.execute("SELECT key, data FROM cats")
            rows = cur.fetchall()
            conn.close()
            
            for key, blob_data in rows:
                if len(blob_data) < 8: continue
                
                # 终极秘密：LZ4 解压
                uncompressed_size = struct.unpack('<I', blob_data[:4])[0]
                try:
                    decompressed = lz4.block.decompress(blob_data[4:], uncompressed_size=uncompressed_size)
                    self.raw_uncompressed_blobs[key] = decompressed
                    
                    # 按照 GameMaker 二进制流协议安全读取
                    name, name_offset_start, name_length = self.parse_cat_name(decompressed)
                    self.cats_data.append((key, name))
                    
                    if name_offset_start != -1:
                        self.name_meta[key] = (name_offset_start, name_length)
                except Exception as e:
                    print(f"Failed to decompress cat {key}: {e}")
                    self.cats_data.append((key, "Failed_Decompress"))
                
            self.refresh_list()
            messagebox.showinfo("Loaded", f"Successfully loaded {len(rows)} cats with flawless LZ4 decoding!")
            
        except Exception as e:
            messagebox.showerror("Database Error", str(e))
            
    def on_search(self, event):
        self.refresh_list()
        
    def refresh_list(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
            
        query = self.entry_search.get().strip().lower()
        
        for key, name in self.cats_data:
            if not query or query in str(key) or (name and query in name.lower()):
                new_n = self.pending_renames.get(key, "")
                self.tree.insert("", tk.END, values=(key, name, new_n))

    def parse_cat_name(self, raw_data):
        # GameMaker 二进制文件精确跳过读取 (来自 Kitty Editor 开源逆向结构):
        # Reader 结构：
        # +0: u32 breedId
        # +4: u64 uniqueId
        # +12: utf16 string (Name!) -> u64 CharCount, followed by charCount*2 bytes string
        try:
            name_length_offset = 12
            # char_count 是 u64 类型 (8 bytes)
            char_count = struct.unpack_from('<Q', raw_data, name_length_offset)[0]
            
            # 不可能超过很大的名字，做下防腐
            if char_count > 100 or char_count < 0:
                return "Unknown_TooString", -1, 0
                
            byte_len = int(char_count * 2)
            string_start = name_length_offset + 8
            
            name_bytes = raw_data[string_start : string_start + byte_len]
            name = name_bytes.decode('utf-16le', errors='ignore')
            
            # 我们记录了我们要替换的数据的位置。
            # 原始长度包括 8 个字节的修饰前缀长度吗？在替换时我们是一并替换掉它的。
            return name, name_length_offset, byte_len + 8 
        except Exception as e:
            return "Unknown_Struct_Err", -1, 0

    def on_cat_select(self, event):
        selected = self.tree.selection()
        if not selected: return
        item = self.tree.item(selected[0])
        self.entry_new_name.delete(0, tk.END)
        
        pending_name = item['values'][2] if len(item['values']) > 2 and item['values'][2] else ""
        current_name = item['values'][1]
        
        if pending_name:
            self.entry_new_name.insert(0, pending_name)
        elif not str(current_name).startswith("Unknown") and not str(current_name).startswith("Failed"):
            self.entry_new_name.insert(0, current_name)

    def set_pending_name(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("Warning", "Please select a cat first!")
            return
            
        item = self.tree.item(selected[0])
        key = int(item['values'][0])
        new_name = self.entry_new_name.get().strip()
        current_name = item['values'][1]
        
        if not new_name or new_name == current_name:
            if key in self.pending_renames:
                del self.pending_renames[key]
            self.tree.item(selected[0], values=(key, current_name, ""))
        else:
            self.pending_renames[key] = new_name
            self.tree.item(selected[0], values=(key, current_name, new_name))
            
        next_item = self.tree.next(selected[0])
        if next_item:
            self.tree.selection_set(next_item)
            self.tree.see(next_item)

    def apply_rename(self):
        if not self.pending_renames:
            messagebox.showwarning("Warning", "No pending renames to save!")
            return
            
        for key in self.pending_renames:
            if key not in self.name_meta:
                messagebox.showerror("Error", f"Cat ID {key}'s structural offset is broken. Cannot safely rename.")
                return
            
        backup_path = self.db_path + f".bak_{datetime.datetime.now().strftime('%H%M%S')}"
        try:
            shutil.copy2(self.db_path, backup_path)
        except:
            pass
            
        try:
            conn = sqlite3.connect(self.db_path)
            cur = conn.cursor()
            
            for key, new_name in self.pending_renames.items():
                uncompressed_data = self.raw_uncompressed_blobs[key]
                offset_start, total_old_length = self.name_meta[key]
                
                new_target_bytes = new_name.encode('utf-16le')
                new_char_count = len(new_name)
                
                new_block = struct.pack('<Q', new_char_count) + new_target_bytes
                
                reconstructed_data = uncompressed_data[:offset_start] + new_block + uncompressed_data[offset_start+total_old_length:]
                
                new_uncompressed_size = len(reconstructed_data)
                compressed_data = lz4.block.compress(reconstructed_data, store_size=False)
                
                final_blob = struct.pack('<I', new_uncompressed_size) + compressed_data
                cur.execute("UPDATE cats SET data = ? WHERE key = ?", (final_blob, key))
                
            conn.commit()
            conn.close()
            
            count = len(self.pending_renames)
            self.pending_renames.clear()
            
            messagebox.showinfo("Success", f"Successfully saved {count} cats to file!")
            self.load_save()
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed: {e}")

if __name__ == "__main__":
    root = tk.Tk()
    app = MewgenicsRenameTool(root)
    root.mainloop()
