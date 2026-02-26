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
        self.root.geometry("820x500") # 稍微加宽一点给滚动条留位置
        
        self.db_path = ""
        self.cats_data = []  
        self.raw_uncompressed_blobs = {} 
        self.name_meta = {} 
        
        # 存储待修改的新名字 {cat_id: new_name_string}
        self.pending_names = {}
        
        # [新增] 记录当前正在编辑的输入框和保存回调函数
        self.current_edit_entry = None
        self.current_save_callback = None
        
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
        self.entry_search.bind("<KeyRelease>", lambda e: self.refresh_list())
        
        # [修改] 新建一个 frame 专门用来放 Treeview 和 滚动条
        frame_tree = ttk.Frame(frame_mid)
        frame_tree.pack(fill=tk.BOTH, expand=True)

        columns = ("key", "name", "new_name")
        self.tree = ttk.Treeview(frame_tree, columns=columns, show="headings", selectmode="browse")
        self.tree.heading("key", text="ID")
        self.tree.heading("name", text="Current Name")
        self.tree.heading("new_name", text="New Name")
        
        self.tree.column("key", width=60, anchor=tk.CENTER)
        self.tree.column("name", width=250, anchor=tk.W)
        self.tree.column("new_name", width=250, anchor=tk.W)
        
        # [新增] 添加垂直滚动条
        scrollbar = ttk.Scrollbar(frame_tree, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # 绑定点击事件
        self.tree.bind("<Button-1>", self.on_item_click)
        
        # [新增] 绑定滚动和窗口调整事件，当视图变化时自动保存并关闭输入框
        self.tree.bind("<MouseWheel>", self.close_edit_box) # Windows/Mac 滚轮
        self.tree.bind("<Button-4>", self.close_edit_box)   # Linux 滚轮向上
        self.tree.bind("<Button-5>", self.close_edit_box)   # Linux 滚轮向下
        self.tree.bind("<Configure>", self.close_edit_box)  # 窗口大小改变

        frame_btm = ttk.Frame(self.root, padding=10)
        frame_btm.pack(fill=tk.X)
        
        self.btn_apply = ttk.Button(frame_btm, text="Save All Changes", command=self.apply_all_renames)
        self.btn_apply.pack(side=tk.LEFT, padx=5)
        ttk.Label(frame_btm, text="* Only rows with a 'New Name' will be updated. Leave blank to skip.", foreground="green").pack(side=tk.LEFT, padx=10)

    # [新增] 强制关闭并保存当前输入框
    def close_edit_box(self, event=None):
        if self.current_save_callback:
            self.current_save_callback()

    def on_item_click(self, event):
        region = self.tree.identify_region(event.x, event.y)
        if region != "cell": return
        
        column = self.tree.identify_column(event.x)
        item_id = self.tree.identify_row(event.y)
        
        if column == "#3": # 点击的是 New Name 列
            self.draw_edit_box(item_id, column)

    def draw_edit_box(self, item_id, column):
        # [新增] 在打开新输入框前，先保存并销毁可能存在的旧输入框
        self.close_edit_box()

        # [新增] 安全检查：如果该行已经滚动到视野外，bbox 会返回空，此时不生成输入框
        bbox = self.tree.bbox(item_id, column)
        if not bbox: return
        x, y, w, h = bbox
        
        current_val = self.tree.item(item_id, "values")[2]
        
        edit_entry = ttk.Entry(self.tree)
        self.current_edit_entry = edit_entry # [新增] 记录当前 entry
        
        edit_entry.insert(0, current_val)
        edit_entry.select_range(0, tk.END)
        edit_entry.focus_set()
        
        def save_edit(event=None):
            # [新增] 避免 FocusOut 和 Return 同时触发导致的重复销毁报错
            if self.current_edit_entry is None: 
                return 
                
            new_val = edit_entry.get().strip()
            cat_key = int(self.tree.item(item_id, "values")[0])
            
            # 更新表格显示
            vals = list(self.tree.item(item_id, "values"))
            vals[2] = new_val
            self.tree.item(item_id, values=vals)
            
            # 记录修改，如果输入为空则从待修改列表中移除
            if new_val:
                self.pending_names[cat_key] = new_val
            else:
                if cat_key in self.pending_names:
                    del self.pending_names[cat_key]
            
            # [新增] 清理状态并销毁控件
            edit_entry.destroy()
            self.current_edit_entry = None
            self.current_save_callback = None

        # [新增] 将保存逻辑挂载到类属性上
        self.current_save_callback = save_edit

        # 绑定回车和失去焦点自动保存
        edit_entry.bind("<Return>", save_edit)
        edit_entry.bind("<FocusOut>", save_edit)
        edit_entry.place(x=x, y=y, width=w, height=h)

    def apply_all_renames(self):
        # 只处理真正填写了名字的条目
        targets = {k: v for k, v in self.pending_names.items() if v}
        
        if not targets:
            messagebox.showinfo("Info", "No new names entered. Nothing to update.")
            return

        confirm = messagebox.askyesno("Confirm", f"Apply name changes to {len(targets)} cats?")
        if not confirm: return

        try:
            # 自动备份
            backup_path = self.db_path + f".bak_{datetime.datetime.now().strftime('%H%M%S')}"
            shutil.copy2(self.db_path, backup_path)

            conn = sqlite3.connect(self.db_path)
            cur = conn.cursor()

            success_count = 0
            for key, new_name in targets.items():
                if key not in self.name_meta or key not in self.raw_uncompressed_blobs:
                    continue
                
                # LZ4 重组逻辑
                uncompressed_data = self.raw_uncompressed_blobs[key]
                offset_start, total_old_length = self.name_meta[key]
                
                new_target_bytes = new_name.encode('utf-16le')
                new_block = struct.pack('<Q', len(new_name)) + new_target_bytes
                
                reconstructed_data = uncompressed_data[:offset_start] + new_block + uncompressed_data[offset_start+total_old_length:]
                new_uncompressed_size = len(reconstructed_data)
                compressed_data = lz4.block.compress(reconstructed_data, store_size=False)
                final_blob = struct.pack('<I', new_uncompressed_size) + compressed_data
                
                cur.execute("UPDATE cats SET data = ? WHERE key = ?", (final_blob, key))
                success_count += 1

            conn.commit()
            conn.close()
            
            messagebox.showinfo("Success", f"Successfully updated {success_count} cats!")
            self.pending_names.clear()
            self.load_save() 

        except Exception as e:
            messagebox.showerror("Error", f"Failed to save: {e}")

    # --- 基础功能函数 ---

    def auto_locate_save(self):
        appdata = os.environ.get('APPDATA')
        if not appdata: return
        base_dir = os.path.join(appdata, "Glaiel Games", "Mewgenics")
        if os.path.exists(base_dir):
            latest_sav = None
            latest_time = 0
            for root, dirs, files in os.walk(base_dir):
                for file in files:
                    if file.endswith('.sav'):
                        fp = os.path.join(root, file)
                        mt = os.path.getmtime(fp)
                        if mt > latest_time:
                            latest_time, latest_sav = mt, fp
            if latest_sav:
                self.entry_path.insert(0, latest_sav)
                self.load_save()

    def browse_file(self):
        path = filedialog.askopenfilename(filetypes=(("Mewgenics Save", "*.sav"), ("All Files", "*.*")))
        if path:
            self.entry_path.delete(0, tk.END)
            self.entry_path.insert(0, path)
            self.load_save()

    def load_save(self):
        self.db_path = self.entry_path.get()
        if not os.path.exists(self.db_path): return
        self.cats_data.clear()
        self.raw_uncompressed_blobs.clear()
        self.name_meta.clear()
        self.pending_names.clear()
        
        try:
            conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
            cur = conn.cursor()
            cur.execute("SELECT key, data FROM cats")
            rows = cur.fetchall()
            conn.close()
            
            for key, blob_data in rows:
                if len(blob_data) < 8: continue
                u_size = struct.unpack('<I', blob_data[:4])[0]
                try:
                    decompressed = lz4.block.decompress(blob_data[4:], uncompressed_size=u_size)
                    self.raw_uncompressed_blobs[key] = decompressed
                    name, offset, length = self.parse_cat_name(decompressed)
                    self.cats_data.append((key, name))
                    if offset != -1: self.name_meta[key] = (offset, length)
                except:
                    self.cats_data.append((key, "Error_LZ4"))
            self.refresh_list()
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def refresh_list(self):
        # [新增] 刷新列表前先保存并销毁输入框，防止搜索过滤时旧输入框报错
        self.close_edit_box() 
        
        for item in self.tree.get_children(): self.tree.delete(item)
        query = self.entry_search.get().strip().lower()
        for key, name in self.cats_data:
            if not query or query in str(key) or query in name.lower():
                # 第三列默认留空，除非你已经在当前会话里填了内容
                new_name_display = self.pending_names.get(key, "")
                self.tree.insert("", tk.END, values=(key, name, new_name_display))

    def parse_cat_name(self, raw_data):
        try:
            off = 12
            count = struct.unpack_from('<Q', raw_data, off)[0]
            if count > 200 or count < 0: return "Unknown", -1, 0
            b_len = int(count * 2)
            name = raw_data[off+8 : off+8+b_len].decode('utf-16le', errors='ignore')
            return name, off, b_len + 8 
        except: return "Err_Struct", -1, 0

if __name__ == "__main__":
    root = tk.Tk()
    app = MewgenicsRenameTool(root)
    root.mainloop()