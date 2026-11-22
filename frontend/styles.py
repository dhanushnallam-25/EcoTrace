"""Visual system: colour tokens, CSS injection, Plotly layout and small HTML components.

Palette: dark navy page (#0B192C) with a lighter navy card surface (#112240), teal brand
accent (#0D9488), slate secondary text. Categorical series colours are the validated
dark-mode reference steps (all pass lightness/chroma/CVD/contrast checks on #112240).
Status colours are reserved for priority bands and always ship with a text label.
"""
from __future__ import annotations

import html

import streamlit as st

NAVY = "#0B192C"
SURFACE = "#112240"
SURFACE_2 = "#16294A"
BORDER = "rgba(255,255,255,0.10)"
GRID = "#1E3354"
AXIS = "#2E4468"
TEAL = "#0D9488"
TEAL_LIGHT = "#2DD4BF"
TEXT = "#F1F5F9"
TEXT_2 = "#CBD5E1"
MUTED = "#94A3B8"

# Validated categorical order (dark steps) — assign in this order, never cycle.
SERIES = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#0ca30c", "#9085e9", "#e66767"]

# Reserved status colours (always paired with a text label).
STATUS = {"High": "#d03b3b", "Medium": "#ec835a", "Low": "#fab219", "good": "#0ca30c"}

# Station-type encoding used on every map + legend.
STATION_COLORS = {
    "matched": "#199e70",      # snapped river vertex
    "unmatched": "#d95926",    # river-type but no reach within snap distance
    "lake": "#3987e5",         # lake / tank (isolated by design)
    "unknown": "#94A3B8",      # unknown type (isolated)
}
BFS_COLOR = "#d95926"
DFS_COLOR = "#9085e9"
SOURCE_COLOR = "#F1F5F9"

CSS = f"""
<style>
:root {{ --navy:{NAVY}; --surface:{SURFACE}; --teal:{TEAL}; --text:{TEXT}; --muted:{MUTED}; }}
.stApp {{ background:{NAVY}; }}
[data-testid="stSidebar"] {{ background:#081322; border-right:1px solid {BORDER}; }}
.block-container {{ padding-top:1.6rem; max-width:1500px; }}
h1, h2, h3, h4 {{ color:{TEXT}; letter-spacing:-0.01em; }}
h1 {{ font-weight:700; }}
.et-hero {{ display:flex; align-items:flex-end; justify-content:space-between; gap:16px; flex-wrap:wrap;
           border-bottom:1px solid {BORDER}; padding-bottom:12px; margin-bottom:18px; }}
.et-hero h1 {{ margin:0; font-size:1.75rem; }}
.et-hero p {{ margin:4px 0 0 0; color:{MUTED}; font-size:0.92rem; }}
.et-kpi {{ background:{SURFACE}; border:1px solid {BORDER}; border-radius:10px; padding:14px 16px; height:100%; }}
.et-kpi .lbl {{ color:{MUTED}; font-size:0.74rem; text-transform:uppercase; letter-spacing:0.06em; }}
.et-kpi .val {{ color:{TEXT}; font-size:1.65rem; font-weight:650; line-height:1.2; margin-top:4px; }}
.et-kpi .sub {{ color:{TEXT_2}; font-size:0.78rem; margin-top:2px; }}
.et-kpi.accent {{ border-left:3px solid {TEAL}; }}
.et-card {{ background:{SURFACE}; border:1px solid {BORDER}; border-radius:10px; padding:14px 16px; margin-bottom:12px; }}
.et-note {{ background:rgba(13,148,136,0.10); border:1px solid rgba(13,148,136,0.35); border-radius:8px;
           padding:10px 14px; color:{TEXT_2}; font-size:0.88rem; margin:6px 0 12px 0; }}
.et-warn {{ background:rgba(236,131,90,0.10); border:1px solid rgba(236,131,90,0.45); border-radius:8px;
           padding:10px 14px; color:{TEXT_2}; font-size:0.88rem; margin:6px 0 12px 0; }}
.et-badge {{ display:inline-block; padding:2px 9px; border-radius:999px; font-size:0.74rem; font-weight:600;
            border:1px solid {BORDER}; margin-right:6px; white-space:nowrap; }}
.et-legend {{ display:flex; flex-wrap:wrap; gap:14px; color:{TEXT_2}; font-size:0.82rem; margin:6px 0 4px 0; }}
.et-legend span.dot {{ display:inline-block; width:10px; height:10px; border-radius:50%; margin-right:6px;
                      vertical-align:middle; box-shadow:0 0 0 2px {SURFACE}; }}
.et-mono {{ font-family:Consolas, 'Cascadia Mono', monospace; font-size:0.82rem; color:{TEXT_2}; }}
.et-section {{ color:{MUTED}; font-size:0.75rem; text-transform:uppercase; letter-spacing:0.08em; margin:18px 0 6px 0; }}
div[data-testid="stMetric"] {{ background:{SURFACE}; border:1px solid {BORDER}; border-radius:10px; padding:10px 14px; }}
</style>
"""


def inject_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def hero(title: str, subtitle: str, right_html: str = "") -> None:
    st.markdown(f"<div class='et-hero'><div><h1>{html.escape(title)}</h1><p>{html.escape(subtitle)}</p></div>"
                f"<div>{right_html}</div></div>", unsafe_allow_html=True)


def kpi(label: str, value, sub: str = "", accent: bool = False) -> str:
    cls = "et-kpi accent" if accent else "et-kpi"
    return (f"<div class='{cls}'><div class='lbl'>{html.escape(label)}</div>"
            f"<div class='val'>{html.escape(str(value))}</div><div class='sub'>{html.escape(sub)}</div></div>")


def kpi_row(cards) -> None:
    cols = st.columns(len(cards))
    for col, card in zip(cols, cards):
        col.markdown(card, unsafe_allow_html=True)


def badge(text: str, color: str, text_color: str = "#FFFFFF") -> str:
    return (f"<span class='et-badge' style='background:{color};color:{text_color};border-color:{color}'>"
            f"{html.escape(text)}</span>")


def band_badge(band: str) -> str:
    icon = {"High": "▲", "Medium": "■", "Low": "▼"}.get(band, "")
    return badge(f"{icon} {band}", STATUS.get(band, MUTED), "#0B0B0B" if band == "Low" else "#FFFFFF")


def data_label(kind: str) -> str:
    colors = {"Government data": "#199e70", "Derived": "#3987e5", "Synthetic": "#c98500", "Illustrative": "#9085e9"}
    return badge(kind, colors.get(kind, MUTED), "#0B0B0B" if kind == "Synthetic" else "#FFFFFF")


def note(text_html: str, warn: bool = False) -> None:
    st.markdown(f"<div class='{'et-warn' if warn else 'et-note'}'>{text_html}</div>", unsafe_allow_html=True)


def section(title: str) -> None:
    st.markdown(f"<div class='et-section'>{html.escape(title)}</div>", unsafe_allow_html=True)


def legend(items) -> None:
    """items: list of (color, label)."""
    st.markdown("<div class='et-legend'>" + "".join(
        f"<div><span class='dot' style='background:{c}'></span>{html.escape(lbl)}</div>" for c, lbl in items)
        + "</div>", unsafe_allow_html=True)


def plotly_layout(fig, title: str = "", height: int = 340, legend_on: bool = True):
    fig.update_layout(
        title=dict(text=title, font=dict(size=14, color=TEXT), x=0, xanchor="left"),
        paper_bgcolor=SURFACE, plot_bgcolor=SURFACE, height=height,
        font=dict(family="Segoe UI, system-ui, sans-serif", color=TEXT_2, size=12),
        margin=dict(l=12, r=12, t=44 if title else 16, b=12),
        legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="right", x=1, bgcolor="rgba(0,0,0,0)",
                    font=dict(color=TEXT_2)) if legend_on else None,
        showlegend=legend_on,
        hoverlabel=dict(bgcolor="#0B192C", bordercolor=TEAL, font=dict(color=TEXT)),
        bargap=0.25,
    )
    fig.update_xaxes(gridcolor=GRID, linecolor=AXIS, zerolinecolor=AXIS, tickfont=dict(color=MUTED),
                     title_font=dict(color=MUTED))
    fig.update_yaxes(gridcolor=GRID, linecolor=AXIS, zerolinecolor=AXIS, tickfont=dict(color=MUTED),
                     title_font=dict(color=MUTED))
    return fig
