import flet as ft
from supabase import create_client, Client
import google.generativeai as genai
import speech_recognition as sr
import json
import threading
import PIL.Image
from datetime import datetime, timedelta
import os

# --- 1. KONFIGURASI API (AMBIL DARI ENVIRONMENT SERVER) ---
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://bzkrxdcdnwucawetsmeg.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImJ6a3J4ZGNkbnd1Y2F3ZXRzbWVnIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjM5ODAwMTcsImV4cCI6MjA3OTU1NjAxN30.zqtp_N1ekrpjNTR7o7c_83kZ0dYMD3nKzA1RUyH8nC4")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "AIzaSyBkLqFMiUAjkiS4KWmFRbBgYyv-VG6qIyU")

# Setup Clients
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('models/gemini-flash-latest')

# --- 2. VARIABEL GLOBAL ---
CURRENT_USER = None # Menyimpan data user yang sedang login {id: 1, nama: "Budi"}
pending_trx = {} 

# --- 3. WARNA & THEME ---
COLOR_PRIMARY = "#3730A3"
COLOR_ACCENT = "#4F46E5"
COLOR_BG = "#F3F4F6"
COLOR_SURFACE = "#FFFFFF"
COLOR_SUCCESS = "#059669"
COLOR_DANGER = "#DC2626"
COLOR_TEXT_MAIN = "#000000"
COLOR_TEXT_SUB = "#4B5563"
COLOR_BORDER = "#D1D5DB"

SHADOW_LIGHT = "#1A000000"    
SHADOW_GLOW = "#663730A3"     
COLOR_GREEN_FADE = "#3310B981" 
COLOR_RED_FADE = "#33EF4444"   

def main(page: ft.Page):
    page.title = "Smart Budgeting AI (Multi-User)"
    page.window_width = 400
    page.window_height = 850
    page.bgcolor = COLOR_BG
    page.padding = 0
    page.theme_mode = ft.ThemeMode.LIGHT
    page.fonts = {"Roboto": "https://github.com/google/fonts/raw/main/apache/roboto/Roboto-Regular.ttf"}
    page.theme = ft.Theme(font_family="Roboto")

    # =================================================================
    # BAGIAN 1: LOGIN & USER MANAGEMENT
    # =================================================================
    
    def init_login_page():
        page.clean()
        
        # Ambil daftar user dari DB
        users_res = supabase.table('users').select("*").execute()
        user_options = [ft.dropdown.Option(key=str(u['id']), text=u['nama']) for u in users_res.data]

        dd_user_select = create_dropdown("Pilih Pengguna", options=user_options)
        txt_new_user = create_input("Buat User Baru (Nama)")
        
        def login_clicked(e):
            global CURRENT_USER
            if not dd_user_select.value:
                show_snack("Pilih user dulu!", COLOR_DANGER); return
            
            # Set User Aktif
            user_id = int(dd_user_select.value)
            user_name = next((u.text for u in user_options if u.key == dd_user_select.value), "User")
            CURRENT_USER = {"id": user_id, "nama": user_name}
            
            show_snack(f"Selamat datang, {user_name}!", COLOR_SUCCESS)
            init_main_app() # Masuk ke Dashboard

        def create_user_clicked(e):
            if not txt_new_user.value: return
            # 1. Buat User
            res = supabase.table('users').insert({"nama": txt_new_user.value}).execute()
            new_id = res.data[0]['id']
            
            # 2. Setup Data Awal untuk User Baru (Rekening & Kategori Default)
            supabase.table('rekening').insert({"user_id": new_id, "saldo": 0}).execute()
            default_cats = [{"user_id": new_id, "nama": "Makan"}, {"user_id": new_id, "nama": "Transport"}]
            supabase.table('opsi_kategori').insert(default_cats).execute()
            
            show_snack("User berhasil dibuat!", COLOR_SUCCESS)
            init_login_page() # Refresh halaman login

        # UI Login
        page.add(
            ft.Container(
                content=ft.Column([
                    ft.Icon(ft.Icons.ACCOUNT_BALANCE_WALLET, size=80, color=COLOR_PRIMARY),
                    ft.Text("Smart Budget", size=24, weight="bold", color=COLOR_PRIMARY),
                    ft.Text("Kelola keuangan bersama", size=12, color=COLOR_TEXT_SUB),
                    ft.Divider(height=20, color="transparent"),
                    ft.Text("Siapa Anda?", weight="bold"),
                    dd_user_select,
                    ft.ElevatedButton("Masuk Aplikasi", on_click=login_clicked, bgcolor=COLOR_PRIMARY, color="white", width=float("inf"), height=45),
                    ft.Divider(),
                    ft.Text("Belum punya akun?", size=12, color=COLOR_TEXT_SUB),
                    txt_new_user,
                    ft.ElevatedButton("Buat Akun Baru", on_click=create_user_clicked, bgcolor=COLOR_SUCCESS, color="white", width=float("inf"), height=45),
                ], horizontal_alignment="center", spacing=15),
                padding=30, alignment=ft.alignment.center, expand=True
            )
        )

    # =================================================================
    # BAGIAN 2: APLIKASI UTAMA (DASHBOARD)
    # =================================================================

    def init_main_app():
        page.clean()
        
        # --- LOGIKA DATABASE (DIFILTER BY USER_ID) ---
        def get_saldo_total():
            try:
                res = supabase.table('rekening').select("saldo").eq('user_id', CURRENT_USER['id']).execute()
                return res.data[0]['saldo'] if res.data else 0
            except: return 0

        def get_kategori_list():
            try:
                res = supabase.table('opsi_kategori').select("*").eq('user_id', CURRENT_USER['id']).execute()
                return [item['nama'] for item in res.data]
            except: return []

        def get_all_budgets():
            try:
                res = supabase.table('pos_anggaran').select("*").eq('user_id', CURRENT_USER['id']).execute()
                return res.data
            except: return []

        def hitung_uang_bebas():
            saldo = get_saldo_total()
            budgets = get_all_budgets()
            total_amplop = sum(item['jumlah'] for item in budgets)
            return saldo - total_amplop, budgets

        def update_saldo_total(nominal_baru):
            supabase.table('rekening').update({"saldo": nominal_baru}).eq('user_id', CURRENT_USER['id']).execute()

        def kurangi_budget(kategori, jumlah_potong):
            res = supabase.table('pos_anggaran').select("*").eq('user_id', CURRENT_USER['id']).eq('kategori', kategori).execute()
            if res.data:
                id_budget = res.data[0]['id']; sisa = res.data[0]['jumlah']
                baru = max(0, sisa - jumlah_potong)
                supabase.table('pos_anggaran').update({"jumlah": baru}).eq('id', id_budget).execute()

        def check_limit(kategori, nominal):
            budget = supabase.table('pos_anggaran').select("*").eq('user_id', CURRENT_USER['id']).eq('kategori', kategori).execute()
            if not budget.data: return None
            
            info = budget.data[0]; batas = info.get('batas_nominal', 0); tipe = info.get('tipe_batas')
            if not batas or batas == 0 or not tipe: return None

            today = datetime.now()
            if tipe == "Harian":
                start = today.strftime("%Y-%m-%dT00:00:00"); end = today.strftime("%Y-%m-%dT23:59:59"); msg = "Hari Ini"
            elif tipe == "Mingguan":
                start = (today - timedelta(days=today.weekday())).strftime("%Y-%m-%dT00:00:00")
                end = today.strftime("%Y-%m-%dT23:59:59"); msg = "Minggu Ini"
            else: return None

            res = supabase.table('transaksi').select("nominal").eq('user_id', CURRENT_USER['id']).eq('kategori', kategori).gte('created_at', start).lte('created_at', end).execute()
            pakai = sum(t['nominal'] for t in res.data)
            if (pakai + nominal) > batas:
                return f"⚠️ MELEBIHI LIMIT {msg.upper()}!\nBatas: {format_currency(batas)}\nSudah: {format_currency(pakai)}"
            return None

        # --- LOGIKA TRANSAKSI ---
        def execute_transaction(data):
            global current_saldo
            try:
                kurangi_budget(data['kategori'], data['nominal'])
                # INSERT dengan USER_ID
                data['user_id'] = CURRENT_USER['id']
                supabase.table('transaksi').insert(data).execute()
                
                update_saldo_total(get_saldo_total() - data['nominal'])
                txt_nominal.value = ""; txt_keterangan.value = ""; dlg_confirm.open = False
                show_snack("Transaksi Berhasil!", COLOR_SUCCESS); refresh_all()
            except Exception as ex: print(ex)

        def check_transaction(e):
            global pending_trx
            if not txt_nominal.value or not dd_kategori.value: return
            data = {"keterangan": txt_keterangan.value, "nominal": int(txt_nominal.value), "kategori": dd_kategori.value}
            
            limit_msg = check_limit(data['kategori'], data['nominal'])
            if limit_msg:
                pending_trx = data; txt_confirm_msg.value = limit_msg; page.open(dlg_confirm); return

            cek = supabase.table('pos_anggaran').select("*").eq('user_id', CURRENT_USER['id']).eq('kategori', data['kategori']).execute()
            if cek.data and data['nominal'] > cek.data[0]['jumlah']:
                pending_trx = data; txt_confirm_msg.value = f"⚠️ Overbudget! Sisa amplop {format_currency(cek.data[0]['jumlah'])}."; page.open(dlg_confirm); return
            
            execute_transaction(data)

        # --- MANAJEMEN DATA (CRUD) ---
        def simpan_saldo(e):
            if set_input_saldo.value:
                masuk = int(set_input_saldo.value); total = get_saldo_total() + masuk
                update_saldo_total(total)
                supabase.table('transaksi').insert({"user_id": CURRENT_USER['id'], "keterangan": "Top Up", "nominal": masuk, "kategori": "Pemasukan"}).execute()
                set_input_saldo.value = ""; show_snack("Top Up Berhasil", COLOR_SUCCESS); refresh_all()

        def tambah_kategori(e):
            if set_input_kategori.value:
                supabase.table('opsi_kategori').insert({"user_id": CURRENT_USER['id'], "nama": set_input_kategori.value}).execute()
                set_input_kategori.value = ""; refresh_all()

        def hapus_kategori(nama):
            supabase.table('opsi_kategori').delete().eq('user_id', CURRENT_USER['id']).eq('nama', nama).execute()
            refresh_all()

        def tambah_amplop(e):
            if not dlg_jml_budget.value: return
            nama = dd_pilih_kategori_budget.value; jml = int(dlg_jml_budget.value)
            batas = int(dlg_limit_nominal.value) if dlg_limit_nominal.value else 0
            tipe = dd_tipe_limit.value
            
            cek = supabase.table('pos_anggaran').select("*").eq('user_id', CURRENT_USER['id']).eq('kategori', nama).execute()
            data_payload = {"user_id": CURRENT_USER['id'], "kategori": nama, "jumlah": jml, "batas_nominal": batas, "tipe_batas": tipe}
            
            if cek.data:
                data_payload['jumlah'] += cek.data[0]['jumlah'] # Tambah saldo lama
                supabase.table('pos_anggaran').update(data_payload).eq('id', cek.data[0]['id']).execute()
            else:
                supabase.table('pos_anggaran').insert(data_payload).execute()
            
            dlg_budget_modal.open = False; refresh_all()

        def hapus_amplop(id_amplop):
            supabase.table('pos_anggaran').delete().eq('id', id_amplop).execute(); refresh_all()

        def open_edit_amplop(data):
            dd_pilih_kategori_budget.value = data['kategori']; dlg_jml_budget.value = "0"
            dlg_limit_nominal.value = str(data.get('batas_nominal', 0)); dd_tipe_limit.value = data.get('tipe_batas', "Tidak Ada")
            page.open(dlg_budget_modal)

        def logout(e):
            init_login_page()

        # --- UI AI (VOICE & VISION) ---
        def process_voice(e):
            btn_mic.icon, btn_mic.bgcolor = ft.Icons.HOURGLASS_TOP, "orange"; page.update()
            def run():
                try:
                    rec = sr.Recognizer()
                    with sr.Microphone() as src:
                        audio = rec.listen(src, timeout=5)
                        txt = rec.recognize_google(audio, language="id-ID")
                        prompt = f"Ekstrak: '{txt}'. Kat: {', '.join(get_kategori_list())}. JSON: {{'nominal': int, 'kategori': str, 'keterangan': str}}"
                        res = model.generate_content(prompt)
                        js = extract_json(res.text)
                        if js: txt_nominal.value, dd_kategori.value, txt_keterangan.value = str(js['nominal']), js['kategori'], js['keterangan']
                        page.update()
                except: pass
                finally: btn_mic.icon, btn_mic.bgcolor = ft.Icons.MIC, COLOR_DANGER; page.update()
            threading.Thread(target=run).start()

        def process_image(e):
            if not e.files: return
            path = e.files[0].path; btn_scan.icon, btn_scan.bgcolor = ft.Icons.HOURGLASS_TOP, "orange"; page.update()
            def run():
                try:
                    img = PIL.Image.open(path)
                    prompt = f"OCR Struk. Kat: {', '.join(get_kategori_list())}. JSON: {{'nominal': int, 'kategori': str, 'keterangan': str}}"
                    res = model.generate_content([prompt, img])
                    js = extract_json(res.text)
                    if js: txt_nominal.value, dd_kategori.value, txt_keterangan.value = str(js['nominal']), js['kategori'], js['keterangan']
                    page.update()
                except: pass
                finally: btn_scan.icon, btn_scan.bgcolor = ft.Icons.CAMERA_ALT, COLOR_SUCCESS; page.update()
            threading.Thread(target=run).start()

        # --- KOMPONEN UI UTAMA ---
        txt_confirm_msg = ft.Text("", color=COLOR_TEXT_MAIN)
        dlg_confirm = ft.AlertDialog(modal=True, title=ft.Text("Konfirmasi"), content=txt_confirm_msg, actions=[ft.TextButton("Batal", on_click=lambda e: page.close(dlg_confirm)), ft.ElevatedButton("Lanjut", on_click=lambda e: execute_transaction(pending_trx), bgcolor=COLOR_DANGER, color="white")], bgcolor=COLOR_SURFACE)
        
        dd_pilih_kategori_budget = create_dropdown("Pilih Kategori")
        dlg_jml_budget = create_input("Top Up (+)", ft.KeyboardType.NUMBER, force_number_only)
        dlg_limit_nominal = create_input("Batas", ft.KeyboardType.NUMBER, force_number_only)
        dd_tipe_limit = create_dropdown("Periode", [ft.dropdown.Option("Harian"), ft.dropdown.Option("Mingguan"), ft.dropdown.Option("Tidak Ada")], "Tidak Ada")
        dlg_budget_modal = ft.AlertDialog(title=ft.Text("Kelola Amplop"), content=ft.Column([dd_pilih_kategori_budget, dlg_jml_budget, dlg_limit_nominal, dd_tipe_limit], height=250), actions=[ft.ElevatedButton("Simpan", on_click=tambah_amplop, bgcolor=COLOR_PRIMARY, color="white")], bgcolor=COLOR_SURFACE)

        txt_total_saldo = ft.Text("Rp 0", size=28, weight="bold", color="white")
        txt_uang_bebas = ft.Text("Uang Bebas: Rp 0", size=14, color="white70")
        header_saldo = ft.Container(content=ft.Column([ft.Row([ft.Text(f"Hai, {CURRENT_USER['nama']}", color="white"), ft.IconButton(ft.Icons.LOGOUT, icon_color="white", on_click=logout, tooltip="Ganti User")], alignment="spaceBetween"), txt_total_saldo, ft.Divider(color="white24"), txt_uang_bebas]), gradient=ft.LinearGradient(colors=[COLOR_PRIMARY, COLOR_ACCENT]), padding=25, border_radius=20, shadow=ft.BoxShadow(blur_radius=15, color=SHADOW_GLOW))

        row_budgets = ft.Row(scroll=ft.ScrollMode.HIDDEN)
        txt_nominal = create_input("Nominal", ft.KeyboardType.NUMBER, force_number_only)
        txt_keterangan = create_input("Keterangan")
        dd_kategori = create_dropdown("Kategori")
        file_picker = ft.FilePicker(on_result=process_image); page.overlay.append(file_picker)
        btn_mic = ft.IconButton(ft.Icons.MIC, icon_color="white", bgcolor=COLOR_DANGER, on_click=process_voice)
        btn_scan = ft.IconButton(ft.Icons.CAMERA_ALT, icon_color="white", bgcolor=COLOR_SUCCESS, on_click=lambda _: file_picker.pick_files(allow_multiple=False, allowed_extensions=["png", "jpg"]))
        list_transaksi = ft.ListView(expand=1, spacing=10)

        # Settings UI
        set_input_saldo = create_input("Input Pemasukan (+)", ft.KeyboardType.NUMBER, force_number_only, True)
        set_input_kategori = create_input("Kategori Baru", expand=True)
        list_settings_kategori = ft.Column(spacing=10, scroll=ft.ScrollMode.AUTO)
        list_settings_amplop = ft.Column(spacing=10, scroll=ft.ScrollMode.AUTO)

        # Tabs
        tab_home = ft.Container(content=ft.Column([header_saldo, ft.Text("Monitor Budget", weight="bold"), row_budgets, ft.Divider(), ft.Row([ft.Container(btn_mic), ft.Container(btn_scan), ft.Text("Input AI", color="grey")], alignment="center"), txt_nominal, txt_keterangan, dd_kategori, ft.Container(ft.ElevatedButton("Simpan Transaksi", on_click=check_transaction, bgcolor=COLOR_PRIMARY, color="white", height=50), width=float("inf")), ft.Divider(), ft.Text("Riwayat", weight="bold"), list_transaksi], scroll=ft.ScrollMode.HIDDEN), padding=20)
        tab_settings = ft.Container(content=ft.Column([create_card(ft.Column([ft.Text("Saldo Utama", weight="bold"), ft.Row([set_input_saldo, ft.IconButton(ft.Icons.ADD_CARD, icon_color=COLOR_PRIMARY, on_click=simpan_saldo)])])), ft.Container(height=10), create_card(ft.Column([ft.Text("Kategori", weight="bold"), ft.Row([set_input_kategori, ft.IconButton(ft.Icons.ADD_CIRCLE, icon_color=COLOR_SUCCESS, on_click=tambah_kategori)]), ft.Container(list_settings_kategori, height=150)])), ft.Container(height=10), create_card(ft.Column([ft.Row([ft.Text("Amplop", weight="bold"), ft.ElevatedButton("Buat Baru", on_click=lambda e: (setattr(dd_pilih_kategori_budget, 'value', None), setattr(dlg_jml_budget, 'value', ""), page.open(dlg_budget_modal)), bgcolor=COLOR_SUCCESS, color="white")], alignment="spaceBetween"), ft.Container(list_settings_amplop, height=200)]))], scroll=ft.ScrollMode.AUTO), padding=20)
        
        t = ft.Tabs(selected_index=0, tabs=[ft.Tab(text="Dashboard", icon=ft.Icons.DASHBOARD, content=tab_home), ft.Tab(text="Pengaturan", icon=ft.Icons.SETTINGS, content=tab_settings)], expand=1, divider_color="transparent", indicator_color=COLOR_PRIMARY, label_color=COLOR_PRIMARY, unselected_label_color=COLOR_TEXT_SUB)

        def refresh_all():
            ub, list_b = hitung_uang_bebas()
            txt_total_saldo.value = format_currency(get_saldo_total()); txt_uang_bebas.value = f"Bebas: {format_currency(ub)}"
            kat_db = get_kategori_list()
            dd_kategori.options = [ft.dropdown.Option(k) for k in kat_db]; dd_pilih_kategori_budget.options = [ft.dropdown.Option(k) for k in kat_db]

            row_budgets.controls.clear()
            if not list_b: row_budgets.controls.append(ft.Text("Tidak ada budget", color="grey"))
            else:
                for b in list_b:
                    limit_txt = f"Limit: {format_currency(b['batas_nominal'])}/{b['tipe_batas'][0]}" if b.get('batas_nominal') else "No Limit"
                    perc = min(1.0, b['jumlah'] / b['batas_nominal']) if b.get('batas_nominal') else 0
                    row_budgets.controls.append(ft.Container(content=ft.Column([ft.Text(b['kategori'], size=12, weight="bold"), ft.Text(format_currency(b['jumlah']), size=14, weight="bold", color=COLOR_PRIMARY), ft.Text(limit_txt, size=10, color="grey"), ft.ProgressBar(value=perc, color=COLOR_PRIMARY, bgcolor="#E0E7FF", height=4)], spacing=2), width=150, height=100, bgcolor=COLOR_SURFACE, border_radius=15, padding=15, shadow=ft.BoxShadow(blur_radius=5, color=SHADOW_LIGHT)))

            list_transaksi.controls.clear()
            # Filter Transaksi BY USER
            data_trx = supabase.table('transaksi').select("*").eq('user_id', CURRENT_USER['id']).order('created_at', desc=True).limit(20).execute().data
            for item in data_trx:
                is_in = item['kategori'] == "Pemasukan"; color = COLOR_SUCCESS if is_in else COLOR_DANGER
                sign = "+" if is_in else "-"; bg = COLOR_GREEN_FADE if is_in else COLOR_RED_FADE
                dt = datetime.fromisoformat(item['created_at'].replace('Z', '+00:00')) + timedelta(hours=7)
                list_transaksi.controls.append(ft.Container(content=ft.Row([ft.Container(ft.Icon(ft.Icons.ARROW_DOWNWARD if is_in else ft.Icons.ARROW_UPWARD, color=color, size=18), bgcolor=bg, padding=10, border_radius=10), ft.Column([ft.Text(item['keterangan'], weight="bold"), ft.Text(f"{item['kategori']} • {dt.strftime('%d %b %H:%M')}", size=11, color="grey")], expand=True), ft.Text(f"{sign} {format_currency(item['nominal'])}", color=color, weight="bold")], alignment="spaceBetween"), bgcolor=COLOR_SURFACE, padding=12, border_radius=12, margin=ft.margin.only(bottom=5), shadow=ft.BoxShadow(blur_radius=2, color=SHADOW_LIGHT)))

            list_settings_kategori.controls.clear(); list_settings_amplop.controls.clear()
            for k in kat_db: list_settings_kategori.controls.append(ft.Container(ft.Row([ft.Text(k, expand=True), ft.IconButton(ft.Icons.DELETE_OUTLINE, icon_color=COLOR_DANGER, on_click=lambda e, x=k: hapus_kategori(x))]), bgcolor=COLOR_BG, padding=10, border_radius=8))
            for b in list_b: list_settings_amplop.controls.append(ft.Container(ft.Row([ft.Column([ft.Text(b['kategori'], weight="bold"), ft.Text(f"Sisa: {format_currency(b['jumlah'])}", size=11)], expand=True), ft.IconButton(ft.Icons.EDIT, icon_color=COLOR_PRIMARY, on_click=lambda e, x=b: open_edit_amplop(x)), ft.IconButton(ft.Icons.DELETE_OUTLINE, icon_color=COLOR_DANGER, on_click=lambda e, x=b['id']: hapus_amplop(b['id']))]), bgcolor=COLOR_BG, padding=10, border_radius=8))
            page.update()

        page.add(t); refresh_all()

    # --- HELPER FUNCTIONS (VIEW) ---
    def create_card(content, padding=20): return ft.Container(content=content, bgcolor=COLOR_SURFACE, padding=padding, border_radius=15, shadow=ft.BoxShadow(blur_radius=10, color=SHADOW_LIGHT))
    def create_input(label, kb=None, chg=None, expand=False): return ft.TextField(label=label, keyboard_type=kb, on_change=chg, expand=expand, border_color=COLOR_BORDER, bgcolor=COLOR_SURFACE, border_radius=10, text_size=14, content_padding=15, text_style=ft.TextStyle(color="black"), label_style=ft.TextStyle(color=COLOR_TEXT_SUB))
    def create_dropdown(label, options=[], value=None): return ft.Dropdown(label=label, options=options, value=value, filled=False, text_style=ft.TextStyle(color="black", weight="bold"), color="black", label_style=ft.TextStyle(color=COLOR_TEXT_SUB), border_color=COLOR_BORDER, border_radius=10, bgcolor=COLOR_SURFACE, expand=True)
    def extract_json(text):
        try:
            start = text.find('{'); end = text.rfind('}') + 1
            if start != -1 and end != 0: return json.loads(text[start:end])
        except: return None
    def force_number_only(e): 
        if not e.control.value.isnumeric() and e.control.value != "": e.control.value = "".join(filter(str.isdigit, e.control.value)); e.control.update()
    def format_currency(amount): return f"Rp {amount:,}".replace(",", ".")
    def show_snack(msg, color): page.snack_bar = ft.SnackBar(ft.Text(msg), bgcolor=color); page.snack_bar.open = True; page.update()

    # Mulai dari Halaman Login
    init_login_page()

ft.app(target=main, view=ft.WEB_BROWSER, port=8000, host="0.0.0.0")