"""Admin tab: confirm/dismiss inbox items, apply the weekly report, clean up unknown
destinations, and manage unconfirmed trade intel. Every action is one GitHub commit
(see store.py) and one row in the Change log."""
import hmac
from datetime import date

import pandas as pd
import streamlit as st

import store
import tracker_logic as t


def _lbl(r):
    return f"{t.fmt_date(r['date'])} · {r['mt']:,} MT" + (f" · ESR-{r['esr']}" if r.get("esr") else "")


def _commit(fn, message):
    try:
        store.update(fn, message)
    except ValueError as e:
        st.error(str(e))
        return
    except Exception as e:  # network / permission
        st.error(f"Could not save: {e}")
        return
    st.session_state["admin_msg"] = message
    st.rerun()


def _gate():
    pw = store.cfg("ADMIN_PASSWORD")
    if not pw:
        st.warning("Admin is locked: set `ADMIN_PASSWORD` in the app secrets.")
        return False
    if st.session_state.get("admin_ok"):
        return True
    entered = st.text_input("Admin password", type="password", key="admin_pw")
    if entered:
        if hmac.compare_digest(entered.encode(), str(pw).encode()):
            st.session_state["admin_ok"] = True
            st.rerun()
        else:
            st.error("Wrong password.")
    return False


def _inbox(data):
    items = data.get("pending", [])
    if not items:
        st.success("Inbox is empty — nothing waiting for review.")
        return
    st.caption("Parsed from the FAS mailbox. Nothing here counts until you approve it. Clean items arrive pre-filled; "
               "'review' items were ambiguous (switch/cancel wording, other destination or year, several amounts), so decide by hand.")
    for p in items:
        with st.container(border=True):
            tag = ":green[clean]" if p["kind"] == "flash" and not p.get("reason") else ":orange[review]"
            st.markdown(f"**{tag} · {p.get('subject') or 'FAS release'}** · received {str(p.get('received', ''))[:16].replace('T', ' ')}")
            st.code(p.get("excerpt", ""), language=None, wrap_lines=True)
            if p.get("reason"):
                st.caption(f"⚠ {p['reason']}")
            with st.form(f"f-{p['id']}"):
                c1, c2, c3, c4 = st.columns([1.2, 1, 1, 1])
                dest = c1.selectbox("Count as", ["China — confirmed flash", "Unknown destinations"],
                                    index=1 if p.get("dest") == "unknown" else 0, key=f"d-{p['id']}")
                d = c2.date_input("Date", date.fromisoformat(p["date"]), key=f"dt-{p['id']}")
                esr = c3.text_input("ESR no.", p.get("esr", ""), key=f"e-{p['id']}")
                mt = c4.number_input("MT", min_value=0, step=1000, value=int(p.get("mt") or 0), key=f"m-{p['id']}")
                note = st.text_input("Footnote (optional)", key=f"n-{p['id']}")
                a, b = st.columns(2)
                ok = a.form_submit_button("Approve", type="primary")
                no = b.form_submit_button("Dismiss (don't count)")
            if ok:
                if not mt or not esr.strip():
                    st.error("Enter the ESR number and MT before approving.")
                else:
                    which = "china" if dest.startswith("China") else "unknown"
                    _commit(lambda x: t.approve_pending(x, p["id"], which, d.isoformat(), esr.strip(), int(mt), note),
                            f"Admin: approve inbox item as {which}")
            if no:
                _commit(lambda x: t.dismiss_pending(x, p["id"], note or "dismissed by admin"), "Admin: dismiss inbox item")


def _weekly(data):
    base = data["baseline"]
    pw = data.get("pending_weekly")
    st.caption(f"Current baseline: **{base['label']}** (cutoff {t.fmt_date(base['cutoff'])}). Applying a new weekly ESR report "
               "replaces the baseline and drops every flash row it covers. You then choose which unknown-destination rows and "
               "intel cargoes it absorbed, so nothing is counted twice.")
    if pw:
        st.info(f"New ESR report ready: **{pw['label']}** — China commitment {pw['total_commitment']:,} MT"
                + (f"; unknown-destination net sales for the week {pw['unknown_net_sales']:+,} MT" if pw.get("unknown_net_sales") is not None else ""))
        if pw.get("unknown_net_sales") is not None and pw["unknown_net_sales"] < 0:
            st.warning(f"Unknown destinations show **{pw['unknown_net_sales']:,} MT** net this week: sales were rebooked out of "
                       "unknown. Tick the unknown-destination rows below that match.")
    else:
        key = store.cfg("FAS_API_KEY")
        if key and st.button("Check ESR for a newer week"):
            import esr
            snap = esr.latest_snapshot(key)
            if snap and snap["cutoff"] > base["cutoff"]:
                _commit(lambda x: x.__setitem__("pending_weekly", {**snap, "fetched": t._now()}), "Admin: fetch weekly ESR snapshot")
            else:
                st.success("No newer weekly report than the current baseline.")
    d0 = pw or {"label": base["label"], "cutoff": base["cutoff"], "outstanding": base["outstanding_sales"], "exports": base["accumulated_exports"]}
    c1, c2, c3, c4 = st.columns([1, 1, 1, 1])
    label = c1.text_input("Report label", d0["label"], key=f"wl-{d0['label']}")
    cutoff = c2.date_input("Week ending (cutoff)", date.fromisoformat(d0["cutoff"]), key=f"wc-{d0['label']}")
    outstanding = c3.number_input("China outstanding sales (MT)", min_value=0, step=1000, value=int(d0["outstanding"]), key=f"wo-{d0['label']}")
    exports = c4.number_input("China accumulated exports (MT)", min_value=0, step=1000, value=int(d0["exports"]), key=f"we-{d0['label']}")
    pv = t.preview_weekly(data, label, cutoff.isoformat(), int(outstanding), int(exports))
    m1, m2 = st.columns(2)
    m1.metric("Confirmed MMT after", t.mmt(pv["confirmed_after"]), f"{(pv['confirmed_after'] - pv['confirmed_before']) / 1e6:+.3f}")
    m2.metric("Grand total MMT after (before further offsets)", t.mmt(pv["grand_after"]), f"{(pv['grand_after'] - pv['grand_before']) / 1e6:+.3f}")
    if pv["absorbed"]:
        st.markdown("**Flash rows this report absorbs (will be removed from the confirmed log):**")
        st.dataframe(pd.DataFrame([{"Date": t.fmt_date(r["date"]), "ESR": r["esr"], "MT": r["mt"]} for r in pv["absorbed"]]),
                     hide_index=True, width="stretch")
    else:
        st.caption("No flash rows are dated on/before this cutoff, so none are absorbed.")
    cands = pv["unknown_candidates"]
    pick = st.multiselect("Unknown-destination rows absorbed/rebooked by this report (will be removed)",
                          [_lbl(r) for r in cands], key=f"wu-{label}")
    intel_n = st.number_input("Intel cargoes confirmed by this report (will be cleared)", 0, data["intel"]["cargoes"], 0, key=f"wi-{label}")
    note = st.text_input("Footnote for removals (optional)", key=f"wn-{label}")
    if st.button("Apply weekly report", type="primary", key="apply-weekly"):
        chosen = [(r["date"], r["mt"]) for r in cands if _lbl(r) in pick]
        _commit(lambda x: t.apply_weekly(x, label, cutoff.isoformat(), int(outstanding), int(exports),
                                         unknown_to_remove=chosen, clear_intel=int(intel_n), note=note),
                f"Admin: apply weekly report {label}")


REASONS = [
    "Rebooked to China (confirmed in the weekly ESR report)",
    "Rebooked to another destination (weekly ESR report)",
    "Absorbed by the weekly ESR report",
    "Duplicate entry",
    "Entered in error",
    "Other (type below)",
]


@st.cache_data(ttl=3600, show_spinner=False)
def _esr_unknown(key):
    import esr
    return esr.unknown_weeks(key)


def _unknown(data):
    rows = t.unknown_review(data)
    base = data["baseline"]
    st.caption(f"**{len(rows)} unknown-destination sales** logged, {t.mmt(sum(r['mt'] for r in rows))} MMT. Rows dated after the "
               f"{base['label']} cutoff ({t.fmt_date(base['cutoff'])}) are **new**; rows on/before it are **covered** by the weekly China "
               "report and may already be counted there. Remove a row only when it was rebooked, absorbed, or is wrong.")

    key = store.cfg("FAS_API_KEY")
    with st.expander("USDA weekly unknown-destination sales (a negative week = sales rebooked out of unknown)"):
        if not key:
            st.caption("Add FAS_API_KEY to the app secrets to show the ESR weekly figures here.")
        else:
            try:
                wk = _esr_unknown(key)
                st.dataframe(pd.DataFrame([{"Week": w["label"], "Net sales MT": w["net_sales"], "Outstanding MT": w["outstanding"]} for w in wk]),
                             hide_index=True, width="stretch",
                             column_config={"Net sales MT": st.column_config.NumberColumn(format="localized"),
                                            "Outstanding MT": st.column_config.NumberColumn(format="localized")})
                out = -sum(w["net_sales"] for w in wk if w["net_sales"] < 0)
                st.caption(f"Rebooked out of unknown so far this marketing year: **{out:,} MT**. USDA does not say which sales moved, so "
                           "match them to the rows below by your own judgement. The log only holds flash sales of 100,000 MT or more, so "
                           "it is smaller than USDA's total unknown outstanding.")
            except Exception as e:
                st.caption(f"Could not load the ESR weekly figures: {e}")

    months = sorted({r["date"][:7] for r in rows})
    month_names = {m: f"{t.d(m + '-01'):%b %Y}" for m in months}
    choices = ["All rows", f"New (after {t.fmt_date(base['cutoff'])})", f"Covered (on/before {t.fmt_date(base['cutoff'])})"] + [month_names[m] for m in months]
    flt = st.selectbox("Show", choices, key="unk-filter")
    if flt == "All rows":
        shown = rows
    elif flt.startswith("New"):
        shown = [r for r in rows if r["status"] == "new"]
    elif flt.startswith("Covered"):
        shown = [r for r in rows if r["status"] == "covered"]
    else:
        m = next(k for k, v in month_names.items() if v == flt)
        shown = [r for r in rows if r["date"].startswith(m)]

    st.dataframe(pd.DataFrame([{"Date": t.fmt_date(r["date"]), "ESR": r["esr"], "MT": r["mt"], "Status": r["status"], "Note": r["note"]}
                               for r in reversed(shown)]),
                 hide_index=True, width="stretch", column_config={"MT": st.column_config.NumberColumn(format="localized")})

    all_shown = st.checkbox(f"Select all {len(shown)} shown", key=f"unk-all-{flt}")
    opts = [_lbl(r) for r in shown]
    # the filter and the select-all state are in the key, or a stale selection from another filter would crash
    pick = st.multiselect("Rows to remove", opts, default=opts if all_shown else [], key=f"unk-pick-{flt}-{all_shown}")
    chosen_rows = [r for r in shown if _lbl(r) in pick]

    reason = st.selectbox("Reason", REASONS, key="unk-reason")
    extra = st.text_input("Extra detail (required for Other)", key="unk-extra")
    note = reason if reason != REASONS[-1] else ""
    note = (f"{note} \u2014 {extra.strip()}" if note and extra.strip() else note or extra.strip())

    total = sum(r["mt"] for r in chosen_rows)
    ok = st.checkbox(f"I have checked these {len(chosen_rows)} rows ({total:,} MT) and want them removed", key=f"unk-ok-{len(chosen_rows)}-{total}")
    if st.button(f"Remove {len(chosen_rows)} row(s)", disabled=not (chosen_rows and note and ok), type="primary", key="unk-rm"):
        chosen = [(r["date"], r["mt"]) for r in chosen_rows]

        def fn(x):
            for iso, mt in chosen:
                t.remove_unknown(x, iso, mt, note=note)
        _commit(fn, f"Admin: remove {len(chosen)} unknown-destination row(s)")


def _intel(data):
    i = data["intel"]
    st.markdown(f"**{i['cargoes']} unconfirmed cargoes** × {i['mt_per_cargo']:,} MT = **{i['cargoes'] * i['mt_per_cargo']:,} MT** · {i['week']}")
    with st.expander("Set the count outright"):
        c1, c2 = st.columns(2)
        n = c1.number_input("Cargoes", 0, 200, i["cargoes"], key="intel-n")
        wk = c2.text_input("Week label", i["week"], key="intel-wk")
        if st.button("Set intel", key="intel-set"):
            _commit(lambda x: t.set_intel(x, int(n), wk if wk != i["week"] else None), "Admin: set trade intel")
    with st.expander("USDA confirmed it — move to a confirmed flash sale", expanded=True):
        c1, c2, c3, c4 = st.columns(4)
        n = c1.number_input("Cargoes to clear", 1, max(i["cargoes"], 1), 1, key="ic-n")
        d = c2.date_input("Flash date", date.today(), key="ic-d")
        esr = c3.text_input("ESR no.", key="ic-e")
        mt = c4.number_input("MT (as reported)", 0, step=1000, value=int(i["mt_per_cargo"]), key="ic-m")
        note = st.text_input("Footnote (optional)", key="ic-note")
        if st.button("Move to confirmed", type="primary", disabled=not (esr.strip() and mt and i["cargoes"]), key="ic-go"):
            _commit(lambda x: t.intel_confirm(x, int(n), d.isoformat(), esr.strip(), int(mt), note), "Admin: intel cargo(es) confirmed")
    with st.expander("Discard cargoes (wrong / cancelled)"):
        n = st.number_input("Cargoes to discard", 1, max(i["cargoes"], 1), 1, key="id-n")
        why = st.text_input("Reason (required)", key="id-why")
        if st.button("Discard", disabled=not (why.strip() and i["cargoes"]), key="id-go"):
            _commit(lambda x: t.intel_discard(x, int(n), why.strip()), "Admin: discard intel cargoes")


def _manual(data):
    st.caption("Add a flash sale by hand (e.g. when the mailbox feed is down).")
    c1, c2, c3, c4 = st.columns([1.3, 1, 1, 1])
    dest = c1.selectbox("Count as", ["China — confirmed flash", "Unknown destinations"], key="man-dest")
    d = c2.date_input("Date", date.today(), key="man-d")
    esr = c3.text_input("ESR no.", key="man-e")
    mt = c4.number_input("MT", 0, step=1000, key="man-m")
    note = st.text_input("Footnote (optional)", key="man-n")
    if st.button("Add", disabled=not (esr.strip() and mt), key="man-go"):
        fn = t.add_china_flash if dest.startswith("China") else t.add_unknown
        _commit(lambda x: fn(x, d.isoformat(), esr.strip(), int(mt), note), "Admin: manual flash entry")


def render():
    if not _gate():
        return
    if not store.configured():
        st.info("Local-file mode (no `GITHUB_TOKEN`): changes write to the local data file only.")
    try:
        data, _ = store.load_fresh()
    except Exception as e:
        st.error(f"Could not load live data: {e}")
        return
    if st.session_state.get("admin_msg"):
        st.success(f"Saved — {st.session_state.pop('admin_msg')}. The public tabs refresh within about a minute.")
    n_in = len(data.get("pending", []))
    wk = " · new" if data.get("pending_weekly") else ""
    tabs = st.tabs([f"Inbox ({n_in})", f"Weekly report{wk}", "Unknown destinations", "Trade intel", "Manual entry"])
    for tab, fn in zip(tabs, (_inbox, _weekly, _unknown, _intel, _manual)):
        with tab:
            fn(data)
