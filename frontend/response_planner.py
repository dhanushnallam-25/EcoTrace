"""Response Planner: triage workflow, field notes, MaxHeap-ordered action queue."""
from __future__ import annotations

from collections import Counter

import pandas as pd
import streamlit as st

from backend.response_planner import ROUTING_NOTICE, ResponseLog, action_queue, recommended_actions
from frontend.common import incident_lookup, incident_option_label, incidents, require_state
from frontend.styles import band_badge, data_label, hero, kpi, kpi_row, note, section
from utils.constants import INCIDENT_STATUSES


def render() -> None:
    state = require_state()
    log = ResponseLog()
    incs = incidents(state)
    lookup = incident_lookup(state)
    hero("Response Planner", "Triage, field-verification notes and an action queue ordered by the MaxHeap",
         data_label("Derived"))
    note("🛈 " + ROUTING_NOTICE, warn=True)

    counts = Counter(log.status(i["incident_id"]) for i in incs)
    high_open = sum(1 for i in incs if i["priority_band"] == "High" and log.status(i["incident_id"]) != "Resolved")
    kpi_row([kpi("Pending", counts.get("Pending", 0), "default status", accent=True),
             kpi("Investigating", counts.get("Investigating", 0), "field team assigned"),
             kpi("Resolved", counts.get("Resolved", 0), "verified & closed"),
             kpi("Open high-priority", high_open, "needs action first")])

    f1, f2, f3 = st.columns(3)
    band = f1.multiselect("Priority band", ["High", "Medium", "Low"], default=["High"])
    status = f2.multiselect("Status", INCIDENT_STATUSES, default=["Pending", "Investigating"])
    rivers_only = f3.checkbox("River stations only (downstream impact applies)", value=False)
    queue = [q for q in action_queue(incs, log, include_resolved="Resolved" in status)
             if q["priority_band"] in band and q["status"] in status
             and (not rivers_only or q["station_type"] == "river")]

    section(f"Action queue — {len(queue)} incident(s), extracted from a MaxHeap (score, then downstream reach)")
    st.dataframe(pd.DataFrame([{"Queue #": k, "Incident": q["incident_id"], "Status": q["status"],
                                "Score": q["priority_score"], "Band": q["priority_band"], "Station": q["station_name"],
                                "Date": q["date"], "Parameter": q["parameter_label"], "Value": q["value"],
                                "Downstream": q["downstream_count"],
                                "Assignee": log.get(q["incident_id"]).get("assignee", "")}
                               for k, q in enumerate(queue[:300], 1)]),
                 hide_index=True, width="stretch", height=300)

    section("Triage an incident")
    ids = [q["incident_id"] for q in queue] or [i["incident_id"] for i in sorted(incs, key=lambda i: -i["priority_score"])]
    pre = st.session_state.get("rp_incident")
    if pre and pre not in ids:
        ids = [pre] + ids
    iid = st.selectbox("Incident", ids, index=ids.index(pre) if pre in ids else 0,
                       format_func=lambda x: incident_option_label(lookup[x]))
    inc = lookup[iid]
    entry = log.get(iid)
    left, right = st.columns([1, 1])
    with left:
        st.markdown(band_badge(inc["priority_band"]) + f" <b>{inc['station_name']}</b> · {inc['parameter_label']} = "
                    f"{inc['value']:g} {inc['unit']} on {inc['date']} · {inc['downstream_count']} downstream station(s)",
                    unsafe_allow_html=True)
        st.markdown("**Recommended actions**")
        for a in recommended_actions(inc):
            st.markdown(f"- {a}")
    with right:
        with st.form(f"triage_{iid}"):
            new_status = st.radio("Status", INCIDENT_STATUSES, index=INCIDENT_STATUSES.index(entry["status"]),
                                  horizontal=True)
            assignee = st.text_input("Assigned to", entry.get("assignee", ""))
            text = st.text_area("Field verification note", placeholder="e.g. Re-sampled 14:00, outfall observed …")
            if st.form_submit_button("Save", type="primary"):
                if new_status == "Resolved" and not (text.strip() or entry["notes"]):
                    st.error("Add a verification note before resolving.")
                else:
                    log.update(iid, status=new_status, note=text, assignee=assignee)
                    st.success("Saved to data/processed/response_log.json")
                    st.rerun()
        if entry["notes"]:
            st.markdown("**Notes history**")
            for n in reversed(entry["notes"]):
                st.caption(f"{n['at']} — {n['text']}")
