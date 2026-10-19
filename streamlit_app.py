"""China Soybean Purchase Tracker — progress toward China's 25 MMT/yr commitment."""
from html import escape

import pandas as pd
import streamlit as st

import admin
import tracker_logic as t

st.set_page_config(page_title="China Soybean Purchase Tracker", page_icon=":material/grain:", layout="wide")

CSS = """
<style>
.stApp{background:#fff}
header[data-testid="stHeader"]{background:#fff}
.block-container{max-width:1150px;padding-top:4rem}
.jt{font-family:Georgia,'Times New Roman',serif;color:#1f2a1c}
.jt *{box-sizing:border-box}
.jt .hdr{display:flex;justify-content:space-between;align-items:flex-start;border-bottom:1px solid #444;padding-bottom:8px;margin-bottom:14px}
.jt h1{font-size:1.7rem;padding:0;line-height:1.2;margin:0;color:#2c3e27;font-weight:700}
.jt .sub{font-family:Arial,sans-serif;font-size:.78rem;color:#555;margin-top:6px}
.jt .brand{font-size:1.05rem;text-align:right;line-height:1.1;color:#2c3e27;white-space:nowrap}
.jt .brand small{display:block;font-size:.55rem;letter-spacing:.12em;color:#6b7a66}
.jt .commit{background:#eef0e8;border-left:4px solid #2c3e27;padding:10px 14px;font-family:Arial,sans-serif;font-size:.82rem;margin-bottom:16px}
.jt .grid{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}
@media(max-width:900px){.jt .grid{grid-template-columns:1fr}}
.jt .card{border:2px solid #2c3e27;border-radius:6px;padding:12px 16px;background:#fff;font-family:Arial,sans-serif}
.jt .card.u{border-color:#c9741a}.jt .card.i{border-color:#2a3f9e}
.jt .card .k{font-size:.72rem;color:#444;letter-spacing:.02em}
.jt .card .n{font-family:Georgia,serif;font-size:2.4rem;font-weight:700;color:#2c3e27;line-height:1.15}
.jt .card.u .n{color:#b9611a}.jt .card.i .n{color:#2a3f9e}
.jt .card .m{font-size:.76rem;color:#555}
.jt .card .p{font-size:.8rem;font-weight:700;margin-top:4px;color:#2c3e27}
.jt .card.u .p{color:#b9611a}.jt .card.i .p{color:#2a3f9e}
.jt .col h2{font-size:1.05rem;margin:14px 0 2px;display:flex;justify-content:space-between;align-items:center;color:#2c3e27}
.jt .col.u h2{color:#b9611a}.jt .col.i h2{color:#2a3f9e}
.jt .tag{white-space:nowrap;margin-left:6px;font-family:Arial,sans-serif;font-size:.62rem;border:1px solid;border-radius:3px;padding:2px 7px;font-weight:700;letter-spacing:.04em}
.jt .desc{font-family:Arial,sans-serif;font-size:.74rem;color:#555;margin-bottom:8px}
.jt .box{font-family:Arial,sans-serif;font-size:.74rem;border:1px solid;border-radius:5px;padding:9px 11px;margin-bottom:10px;line-height:1.4}
.jt .box.u{background:#fdf3e6;border-color:#c9741a}.jt .box.i{background:#eaf1fb;border-color:#2a3f9e}
.jt .lt{font-family:Arial,sans-serif;font-size:.66rem;letter-spacing:.06em;font-weight:700;color:#555;margin:8px 0 3px}
.jt table{width:100%;border-collapse:collapse;font-family:Arial,sans-serif;font-size:.78rem}
.jt th{font-size:.62rem;letter-spacing:.06em;color:#666;text-align:right;border-bottom:1px solid #999;padding:3px 4px}
.jt th:first-child,.jt td:first-child{text-align:left}
.jt td{text-align:right;padding:5px 4px;border-bottom:1px solid #e6e6e6;font-variant-numeric:tabular-nums}
.jt tr.star td{background:#fbf1dc}
.jt tr.tot td{font-weight:700;border-top:2px solid #333;border-bottom:none}
.jt .star-i{color:#c9741a}
.jt .fn{margin-top:8px}
.jt .fn p{font-family:Arial,sans-serif;font-size:.65rem;color:#555;line-height:1.45;margin:0 0 3px}
.jt .comb{background:#2c3e27;color:#fff;border-radius:6px;padding:12px 16px;margin-top:14px;font-family:Arial,sans-serif}
.jt .comb .h{font-family:Arial,sans-serif;font-size:.68rem;letter-spacing:.06em;font-weight:700;margin-bottom:8px}
.jt .comb .r{display:flex;justify-content:space-between;font-size:.82rem;padding:3px 0}
.jt .comb .r b{font-family:Georgia,serif;font-size:1.05rem}
.jt .comb .g{display:flex;justify-content:space-between;border-top:1px solid #8a9a85;margin-top:6px;padding-top:6px;align-items:baseline}
.jt .comb .g b{font-family:Georgia,serif;font-size:1.4rem}
.jt .comb .pc{font-family:Georgia,serif;font-size:2.4rem;font-weight:700;color:#e8793a}
.jt .comb .pc small{font-family:Arial,sans-serif;font-size:.78rem;color:#fff;font-weight:700}
.jt .src{font-family:Arial,sans-serif;font-size:.66rem;color:#444;border-top:1px solid #444;margin-top:22px;padding-top:8px;line-height:1.5}
</style>
"""


def num(n):
    return f"{n:,}"


def esr_ref(r):
    return f"FAS ESR-{r['esr']}-26" if r.get("esr") else "USDA flash sale"


def build(data):
    s = t.summarize(data)
    base = data["baseline"]
    bl = base["label"]
    g = t.GOAL_MT
    intel = data["intel"]
    my = data["marketing_year"]
    as_of = t.d(data["as_of"])
    as_of_txt = f"{as_of:%B} {as_of.day}, {as_of.year}"

    fl = s["flash"]
    if not fl:
        flash_span = ""
    elif len(fl) == 1 or fl[0]["date"][:7] == fl[-1]["date"][:7]:
        a, b = t.d(fl[0]["date"]), t.d(fl[-1]["date"])
        flash_span = f" + {a:%b} {a.day}–{b.day} flash" if a != b else f" + {a:%b} {a.day} flash"
    else:
        flash_span = f" + {t.fmt_date(fl[0]['date'])}–{t.fmt_date(fl[-1]['date'])} flash"

    # --- confirmed table + footnotes
    crow = [
        f'<tr class="star"><td>{escape(bl)} outstanding <span class="star-i">&#9733;</span></td>'
        f'<td>{num(s["baseline_mt"])}</td><td>{num(s["baseline_mt"])}</td></tr>'
    ]
    cfoot = [
        f'<p><span class="star-i">&#9733;</span> {escape(bl)} ESR outstanding — official {escape(base["source"])} for China, '
        f'MY {my} (Outstanding Sales {num(base["outstanding_sales"])} MT + Accumulated Exports '
        f'{num(base["accumulated_exports"])} MT = Total Commitment {num(s["baseline_mt"])} MT).</p>'
    ]
    for r in s["flash"]:
        crow.append(f"<tr><td>{t.fmt_date(r['date'])} (flash)</td><td>{num(r['mt'])}</td><td>{num(r['running'])}</td></tr>")
        cfoot.append(
            f"<p>{esr_ref(r)} ({t.fmt_date(r['date'])}): {num(r['mt'])} MT soybeans confirmed direct to China — "
            f"post-cutoff flash sale, layered on top of the {escape(bl)} baseline. {escape(r['note'])}</p>"
        )
    if base.get("note"):
        cfoot.append(f"<p>{escape(base['note'])}</p>")
    crow.append(f'<tr class="tot"><td>Total Confirmed</td><td>{num(s["confirmed_mt"])}</td><td>{t.mmt(s["confirmed_mt"])} MMT</td></tr>')

    # --- unknown table + footnotes
    urows = s["unknown"]
    urow = []
    for k, r in enumerate(urows):
        last = k == len(urows) - 1
        star = ' <span class="star-i">&#9733;</span>' if last else ""
        urow.append(
            f'<tr class="{"star" if last else ""}"><td>{t.fmt_date(r["date"])}{star}</td>'
            f'<td>{num(r["mt"])}</td><td>{num(r["running"])}</td></tr>'
        )
    urow.append(f'<tr class="tot"><td>Total</td><td>{num(s["unknown_mt"])}</td><td>{t.mmt(s["unknown_mt"])} MMT</td></tr>')
    ufoot = []
    for k, r in enumerate(reversed(urows)):
        if not (r.get("esr") or r.get("note")) and k:
            continue
        star = '<span class="star-i">&#9733;</span> ' if k == 0 else ""
        ufoot.append(
            f"<p>{star}{esr_ref(r)} ({t.fmt_date(r['date'])}): {num(r['mt'])} MT soybeans to unknown destinations. {escape(r['note'])}</p>"
        )
    for r in data["unknown_removed"]:
        ufoot.append(f"<p>{esr_ref(r)} ({t.fmt_date(r['date'])}): {num(r['mt'])} MT {escape(r['note'])}</p>")

    # --- intel
    icargo = intel["cargoes"] * intel["mt_per_cargo"]
    irow = (
        f'<tr class="star"><td>{escape(intel["week"])} <span class="star-i">&#9733;</span></td>'
        f'<td>{intel["cargoes"]}</td><td>{num(icargo)}</td><td>{num(icargo)}</td></tr>'
        f'<tr class="tot"><td>Total</td><td>{intel["cargoes"]}</td><td>{num(icargo)}</td><td>{t.mmt(icargo)} MMT</td></tr>'
    )

    return f"""
<div class="jt" id="snap-tracker">
 <div class="hdr"><div><h1>China Soybean Purchase Tracker — {my} Marketing Year</h1>
  <div class="sub">U.S. Soybean Export Flash Sales &amp; Weekly Export Sales \xb7 USDA FAS \xb7 White House Fact Sheet \xb7 {as_of_txt}</div></div>
  <div class="brand">John Stewart<small>AND ASSOCIATES</small></div></div>
 <div class="commit"><b>Commitment:</b> Per the Nov. 1, 2025 White House Fact Sheet, China committed to purchase at least <b>25 MMT</b> of U.S. soybeans annually in 2026, 2027, and 2028. The {my} MY opens Sep. 1, 2026. No formal phase structure announced.</div>

 <div class="grid">
  <div class="card"><div class="k">{my[2:]} — CHINA CONFIRMED (USDA)</div><div class="n">{t.mmt(s['confirmed_mt'])}</div>
   <div class="m">MMT \xb7 {escape(bl)}{flash_span}</div><div class="p">{t.pct(s['confirmed_mt'])}% of 25 MMT goal</div></div>
  <div class="card u"><div class="k">{my[2:]} — UNKNOWN DESTINATIONS</div><div class="n">{t.mmt(s['unknown_mt'])}</div>
   <div class="m">MMT \xb7 {len(urows)} flash sales \xb7 may → China</div><div class="p">{t.pct(s['unknown_mt'])}% potential additional</div></div>
  <div class="card i"><div class="k">{my[2:]} — UNCONFIRMED (TRADE INTEL)</div><div class="n">{t.mmt(icargo)}</div>
   <div class="m">MMT \xb7 {intel['cargoes']} cargoes \xb7 {escape(intel['week'].lower())}</div><div class="p">{t.pct(icargo)}% if confirmed to China</div></div>
 </div>

 <div class="grid">
  <div class="col"><h2>China Confirmed <span class="tag">USDA VERIFIED</span></h2>
   <div class="desc">{escape(bl)} outstanding + post-cutoff flash sales confirmed to China for {my} MY.</div>
   <div class="lt">FLASH SALES &amp; OUTSTANDING LOG</div>
   <table><tr><th>DATE / SOURCE</th><th>MT</th><th>RUNNING</th></tr>{''.join(crow)}</table>
   <div class="fn">{''.join(cfoot)}</div></div>

  <div class="col u"><h2>Unknown Destinations <span class="tag">{len(urows)} SALES</span></h2>
   <div class="desc">Unspecified buyers — frequently resolve to China.</div>
   <div class="box u">USDA reports sales to "unknown destinations" when the buyer is not yet identified. These frequently resolve to China and are tracked separately until rebooked.</div>
   <div class="lt">UNKNOWN DESTINATION LOG</div>
   <table><tr><th>DATE</th><th>MT</th><th>RUNNING</th></tr>{''.join(urow)}</table>
   <div class="fn">{''.join(ufoot)}</div></div>

  <div class="col i"><h2>Unconfirmed — Trade Intel <span class="tag">PRE-USDA</span></h2>
   <div class="desc">{escape(intel['week'])} — awaiting USDA confirmation.</div>
   <div class="box i">Cargo-based estimates at {num(intel['mt_per_cargo'])} MT per cargo. Trade intelligence only — not verified by USDA. Entries cleared as USDA flash sales confirm the same cargoes.</div>
   <div class="lt">UNCONFIRMED CARGO LOG</div>
   <table><tr><th>WEEK</th><th>CARGOES</th><th>EST. MT</th><th>RUNNING</th></tr>{irow}</table>
   <div class="fn"><p><span class="star-i">&#9733;</span> Trade intel set to {intel['cargoes']} vessels, {escape(intel['week'].lower())}. Not yet USDA-confirmed. Basis: {num(intel['mt_per_cargo'])} MT per vessel/cargo.</p></div>
   <div class="comb"><div class="h">{my[2:]} COMBINED TOTAL</div>
    <div class="r"><span>Confirmed (USDA)</span><b>{t.mmt(s['confirmed_mt'])} MMT</b></div>
    <div class="r"><span>+ Unknown Destinations</span><b style="color:#e8a24a">{t.mmt(s['unknown_mt'])} MMT</b></div>
    <div class="r"><span>+ Trade Intel</span><b style="color:#8fb0ff">{t.mmt(icargo)} MMT</b></div>
    <div class="g"><span><b style="font-size:1rem">Grand Total</b></span><b>{t.mmt(s['grand_mt'])} MMT</b></div>
    <div class="pc">{t.pct(s['grand_mt'])}% <small>of 25 MMT goal</small></div></div>
  </div>
 </div>

 <div class="src"><b>Sources:</b> {escape(data['sources'])}</div>
</div>
"""


SNAP_JS = """
<div style="display:flex;gap:6px;align-items:center;margin:2px 0 10px 0">
  <button id="dlSNAP" style="font:600 13px system-ui,sans-serif;color:#fff;background:#2c3e27;border:none;border-radius:6px;padding:6px 12px;cursor:pointer">📥 Download PNG</button>
  <button id="cpSNAP" style="font:600 13px system-ui,sans-serif;color:#2c3e27;background:transparent;border:1.5px solid #2c3e27;border-radius:6px;padding:6px 12px;cursor:pointer">📋 Copy image</button>
  <span id="msgSNAP" style="font:12px system-ui,sans-serif;color:#666"></span>
</div>
<script>
(function(){
  const ID="snap-tracker", FN="__FN__";
  function ensureH2C(){
    if(window.html2canvas) return Promise.resolve();
    if(window.__h2c) return window.__h2c;
    window.__h2c=new Promise((res,rej)=>{
      const s=document.createElement("script");
      s.src="https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js";
      s.onload=()=>res(); s.onerror=()=>rej(new Error("load failed"));
      document.head.appendChild(s); setTimeout(()=>rej(new Error("timeout")),10000);
    });
    return window.__h2c;
  }
  async function shoot(){
    await ensureH2C();
    const el=document.getElementById(ID); if(!el) throw new Error("nothing to capture");
    return await window.html2canvas(el,{scale:2,backgroundColor:"#ffffff",logging:false,useCORS:true});
  }
  const msgEl=document.getElementById("msgSNAP");
  const msg=t=>{ if(msgEl){ msgEl.textContent=t; if(t) setTimeout(()=>{msgEl.textContent="";},2500);} };
  document.getElementById("dlSNAP").onclick=async()=>{
    msg("…"); try{ const c=await shoot(); const a=document.createElement("a");
      a.download=FN+".png"; a.href=c.toDataURL("image/png"); a.click(); msg("✓ saved"); }
    catch(e){ msg("⚠ "+e.message); }
  };
  // Promise-based ClipboardItem keeps the click's user gesture through html2canvas.
  document.getElementById("cpSNAP").onclick=async()=>{
    msg("…");
    try{
      await navigator.clipboard.write([new ClipboardItem({"image/png":(async()=>{
        const c=await shoot();
        return await new Promise(r=>c.toBlob(r,"image/png"));
      })()})]);
      msg("✓ copied");
    }catch(e){ msg("⚠ "+(e.name||e.message)); }
  };
})();
</script>
"""


def included_tables(data):
    s = t.summarize(data)
    base = data["baseline"]
    conf = [{"Date": base["label"], "Source": base["source"], "MT": s["baseline_mt"],
             "Running MT": s["baseline_mt"], "Note": f"Outstanding {base['outstanding_sales']:,} + exports {base['accumulated_exports']:,}"}]
    conf += [{"Date": t.fmt_date(r["date"]), "Source": esr_ref(r), "MT": r["mt"], "Running MT": r["running"], "Note": r["note"]} for r in s["flash"]]
    unk = [{"Date": t.fmt_date(r["date"]), "Source": esr_ref(r), "MT": r["mt"], "Running MT": r["running"], "Note": r["note"]} for r in s["unknown"]]
    rem = [{"Date": t.fmt_date(r["date"]), "Source": esr_ref(r), "MT": r["mt"], "Note": r["note"]} for r in data["unknown_removed"]]
    exc = [{"Date": t.fmt_date(r["date"]), "Source": f"FAS ESR-{r['esr']}-26", "Commodity": r["commodity"],
            "Destination": r["destination"], "MT": r["mt"], "Reason": r["reason"]} for r in data["excluded"]]
    return conf, unk, rem, exc


def log_table(data):
    rows = []
    for r in reversed(data.get("log", [])):
        rows.append({"When (CT)": r["ts"].replace("T", " ")[:16], "Change": r["action"], "Detail": r["detail"],
                     "Confirmed": t.mmt(r["confirmed"]), "Unknown": t.mmt(r["unknown"]),
                     "Intel": t.mmt(r["intel"]), "Grand total": t.mmt(r["grand"])})
    return pd.DataFrame(rows)


NUM = st.column_config.NumberColumn(format="localized")

data = t.load()
tab_snap, tab_in, tab_log, tab_admin = st.tabs(["Snapshot", "What’s included", "Change log", "Admin"])

with tab_snap:
    st.html(SNAP_JS.replace("__FN__", f"China Soybean Tracker {data['as_of']}"), unsafe_allow_javascript=True)
    st.html(CSS + build(data))

with tab_in:
    conf, unk, rem, exc = included_tables(data)
    st.caption("Every row feeding the snapshot. Only soybeans count; corn and meal are excluded.")
    st.subheader("China confirmed (USDA)")
    st.dataframe(pd.DataFrame(conf), hide_index=True, width="stretch", column_config={"MT": NUM, "Running MT": NUM})
    st.subheader(f"Unknown destinations ({len(unk)} sales)")
    st.dataframe(pd.DataFrame(unk), hide_index=True, width="stretch", column_config={"MT": NUM, "Running MT": NUM})
    st.subheader("Trade intel (unconfirmed)")
    i = data["intel"]
    st.write(f"{i['cargoes']} cargoes × {i['mt_per_cargo']:,} MT = **{i['cargoes'] * i['mt_per_cargo']:,} MT** · {i['week']}")
    st.subheader("Removed from the unknown-destination log")
    st.dataframe(pd.DataFrame(rem), hide_index=True, width="stretch", column_config={"MT": NUM})
    st.subheader("Excluded as out of scope")
    st.dataframe(pd.DataFrame(exc), hide_index=True, width="stretch", column_config={"MT": NUM})

with tab_log:
    st.caption("Every update made through update_tracker.py, newest first, with the totals (MMT) after each change.")
    lt = log_table(data)
    if lt.empty:
        st.info("No changes logged yet.")
    else:
        st.dataframe(lt, hide_index=True, width="stretch")

with tab_admin:
    admin.render()
