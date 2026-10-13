import time
import html
import requests
import pandas as pd
import folium
import streamlit as st
from concurrent.futures import ThreadPoolExecutor
from streamlit_folium import st_folium

NM = 1.852
MAX_PLANES = 10
st.set_page_config(page_title="Planes overhead", page_icon="✈️", layout="wide")

st.markdown("""
<style>
.stApp, header[data-testid="stHeader"] { background-color: #ffffff; }
.stApp p, .stApp h1, .stApp h2, .stApp h3, .stApp label, .stApp div[data-testid="stCaptionContainer"] { color: #111827 !important; }

iframe[title="streamlit_folium.st_folium"] {
    background: #ffffff !important;
    border: 1px solid #e5e7eb;
    border-radius: 12px;
}

/* credit line under the title */
.credit {
    font-family: "Segoe UI", Arial, sans-serif;
    font-size: 14px;
    color: #6b7280;
    margin: -8px 0 12px 0;
}
.credit a { color: #1a73e8; text-decoration: none; }
.credit a:hover { text-decoration: underline; }

/* search box: white in every state (normal, hover, focus, typing) */
[data-testid="stTextInput"],
[data-testid="stTextInput"] div,
[data-testid="stTextInputRootElement"],
[data-testid="stTextInputRootElement"] > div {
    background-color: #ffffff !important;
}
[data-testid="stTextInputRootElement"] {
    border: 1px solid #d1d5db !important;
    border-radius: 8px !important;
}
[data-testid="stTextInputRootElement"]:focus-within {
    border: 1px solid #1a73e8 !important;
    box-shadow: none !important;
}
[data-testid="stTextInput"] input {
    background-color: #ffffff !important;
    color: #000000 !important;
    -webkit-text-fill-color: #000000 !important;
    caret-color: #000000 !important;
}
[data-testid="stTextInput"] input::placeholder {
    color: #6b7280 !important;
    -webkit-text-fill-color: #6b7280 !important;
}
[data-testid="InputInstructions"], [data-testid="InputInstructions"] * {
    color: #6b7280 !important;
    background: transparent !important;
}

/* search button: white in every state */
[data-testid="stFormSubmitButton"] button,
[data-testid="stFormSubmitButton"] button:hover,
[data-testid="stFormSubmitButton"] button:active,
[data-testid="stFormSubmitButton"] button:focus {
    background-color: #ffffff !important;
    border: 1px solid #d1d5db !important;
    box-shadow: none !important;
}
[data-testid="stFormSubmitButton"] button:hover { background-color: #f3f4f6 !important; }
[data-testid="stFormSubmitButton"] button * { color: #000000 !important; }

/* radius buttons */
[data-testid="stButtonGroup"], [data-testid="stSegmentedControl"] {
    background: transparent !important;
}
[data-testid="stButtonGroup"] button,
[data-testid="stSegmentedControl"] button {
    background-color: #ffffff !important;
    border: 1px solid #d1d5db !important;
}
[data-testid="stButtonGroup"] button *,
[data-testid="stSegmentedControl"] button * {
    color: #000000 !important;
}
[data-testid="stButtonGroup"] button[kind="segmented_controlActive"],
[data-testid="stButtonGroup"] button[aria-checked="true"],
[data-testid="stSegmentedControl"] button[aria-checked="true"] {
    background-color: #e8f0fe !important;
    border: 2px solid #1a73e8 !important;
}

/* flights table */
.table-wrap {
    max-height: 650px;
    overflow: auto;
    border: 1px solid #e5e7eb;
    border-radius: 12px;
    background: #ffffff;
}
table.flights {
    width: 100%;
    border-collapse: collapse;
    font-family: "Segoe UI", Arial, sans-serif;
    font-size: 14px;
    color: #111827;
}
table.flights th {
    position: sticky; top: 0;
    background: #f9fafb;
    text-align: left;
    padding: 10px 12px;
    font-weight: 600;
    color: #374151;
    border-bottom: 1px solid #e5e7eb;
    white-space: nowrap;
}
table.flights td {
    padding: 9px 12px;
    border-bottom: 1px solid #f3f4f6;
    background: #ffffff;
    white-space: nowrap;
}
table.flights tr:hover td { background: #f5f9ff; }
table.flights td.flight { font-weight: 600; color: #1a73e8; }
table.flights img.flag {
    width: 20px; height: 15px;
    margin-right: 6px;
    vertical-align: -2px;
    border: 1px solid #e5e7eb;
    border-radius: 2px;
}
</style>
""", unsafe_allow_html=True)

st.title("✈️ Planes in the sky near you")
st.markdown(
    '<div class="credit">Made by <a href="https://github.com/beridzeg45" target="_blank">Giorgi Beridze</a>'
    ' · <a href="https://github.com/beridzeg45" target="_blank">GitHub</a></div>',
    unsafe_allow_html=True,
)

if "loc" not in st.session_state:
    st.session_state.loc = None
if "center" not in st.session_state:
    st.session_state.center = [42.0, 43.5]
    st.session_state.zoom = 6

UNKNOWN = ("unknown", "unknown", "", "unknown", "unknown", "")


@st.cache_resource
def route_cache_v3():
    return {}


def get_route(callsign, cache):
    entry = cache.get(callsign)
    if entry:
        result, saved_at = entry
        # remember "no route" for 10 minutes so it isn't looked up again
        if result != UNKNOWN or time.time() - saved_at < 600:
            return result
    try:
        fr = requests.get(
            f"https://api.adsbdb.com/v0/callsign/{callsign}", timeout=5
        ).json()["response"]["flightroute"]
        o, d = fr["origin"], fr["destination"]
        result = (
            o["municipality"], o["country_name"], o.get("country_iso_name") or "",
            d["municipality"], d["country_name"], d.get("country_iso_name") or "",
        )
    except (KeyError, TypeError):
        result = UNKNOWN  # adsbdb has no route for this flight
    except (ValueError, requests.RequestException):
        return UNKNOWN  # network problem, don't remember it
    cache[callsign] = (result, time.time())
    return result


def geocode(query):
    """Find a place by name using OpenStreetMap Nominatim."""
    try:
        r = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": query, "format": "json", "limit": 1},
            headers={"User-Agent": "planes-overhead-streamlit-app"},
            timeout=10,
        ).json()
        if r:
            return float(r[0]["lat"]), float(r[0]["lon"])
    except (ValueError, KeyError, requests.RequestException):
        pass
    return None


def flag_html(iso):
    if not iso:
        return ""
    return f'<img class="flag" src="https://flagcdn.com/40x30/{html.escape(iso.lower())}.png" alt="">'


def to_meters(alt):
    try:
        return round(float(alt) * 0.3048)
    except (TypeError, ValueError):
        return ""


def render_table(df):
    cols = [c for c in df.columns if not c.startswith("_")]
    head = "".join(f"<th>{html.escape(c)}</th>" for c in cols)
    body = ""
    for _, r in df.iterrows():
        cells = ""
        for c in cols:
            text = html.escape(str(r[c]))
            if c == "From country":
                cells += f"<td>{flag_html(r['_from_iso'])}{text}</td>"
            elif c == "To country":
                cells += f"<td>{flag_html(r['_to_iso'])}{text}</td>"
            elif c == "Flight":
                cells += f'<td class="flight">{text}</td>'
            else:
                cells += f"<td>{text}</td>"
        body += f"<tr>{cells}</tr>"
    st.markdown(
        f'<div class="table-wrap"><table class="flights"><thead><tr>{head}</tr></thead>'
        f"<tbody>{body}</tbody></table></div>",
        unsafe_allow_html=True,
    )


def render_plane_map(lat, lon, radius_km, df):
    m2 = folium.Map(location=[lat, lon], zoom_start=8)
    folium.Marker(
        [lat, lon], tooltip="Your location",
        icon=folium.Icon(color="red", icon="home"),
    ).add_to(m2)
    folium.Circle(
        [lat, lon], radius=radius_km * 1000,
        color="#1a73e8", weight=1, fill=True, fill_opacity=0.04,
    ).add_to(m2)

    points = [[lat, lon]]
    for _, r in df.iterrows():
        if pd.isna(r["Lat"]) or pd.isna(r["Lon"]):
            continue
        iso = r["_to_iso"]
        if iso:
            inner = (
                f'<img src="https://flagcdn.com/40x30/{html.escape(iso.lower())}.png" '
                'style="width:28px;height:21px;border:1px solid #fff;'
                'box-shadow:0 0 3px rgba(0,0,0,0.6);">'
            )
        else:
            inner = '<div style="font-size:20px;">✈️</div>'
        tip = html.escape(
            f"{r['Flight']} · {r['From city']} → {r['To city']} · {r['Altitude (m)']} m"
        )
        folium.Marker(
            [r["Lat"], r["Lon"]],
            icon=folium.DivIcon(html=inner, icon_size=(28, 21), icon_anchor=(14, 10)),
            tooltip=tip,
        ).add_to(m2)
        points.append([r["Lat"], r["Lon"]])

    if len(points) > 1:
        # bigger padding = the map starts a bit more zoomed out
        m2.fit_bounds(points, padding=(110, 110), max_zoom=7)
    st_folium(m2, key="planes_map", use_container_width=True, height=550, returned_objects=[])


def load_rows(lat, lon, radius_km):
    """Fetch planes, keep only the closest ones that have a known route."""
    radius_nm = radius_km / NM
    try:
        ac = requests.get(
            f"https://api.adsb.lol/v2/point/{lat}/{lon}/{radius_nm:.0f}", timeout=10
        ).json()["ac"]
    except (ValueError, KeyError, requests.RequestException):
        return None

    candidates = [
        p for p in ac
        if p.get("alt_baro") != "ground" and (p.get("flight") or "").strip()
    ]
    candidates.sort(key=lambda p: p["dst"] if p.get("dst") is not None else 1e9)

    # look up routes for the 20 closest planes at the same time
    top = candidates[: MAX_PLANES * 2]
    cache = route_cache_v3()
    with ThreadPoolExecutor(max_workers=10) as pool:
        routes = list(pool.map(lambda p: get_route(p["flight"].strip(), cache), top))

    rows = []
    for p, route in zip(top, routes):
        if len(rows) >= MAX_PLANES:
            break
        from_city, from_country, from_iso, to_city, to_country, to_iso = route
        if from_city == "unknown" or to_city == "unknown":
            continue
        rows.append({
            "Flight": p["flight"].strip(),
            "Altitude (m)": to_meters(p.get("alt_baro")),
            "Lat": p.get("lat"),
            "Lon": p.get("lon"),
            "Distance (km)": round(p.get("dst", 0) * NM, 1),
            "From city": from_city,
            "From country": from_country,
            "To city": to_city,
            "To country": to_country,
            "_from_iso": from_iso,
            "_to_iso": to_iso,
        })
    return rows


@st.fragment(run_every=15)
def show_flights(lat, lon, radius_km):
    # 1) loading message while data is fetched
    with st.spinner("⏳ Loading flights, please wait..."):
        rows = load_rows(lat, lon, radius_km)

    if rows is None:
        st.error("Could not load flights, will retry in a minute.")
        return

    key = (lat, lon, radius_km)
    current = {r["Flight"] for r in rows}
    if st.session_state.get("seen_key") == key:
        for cs in current - st.session_state.get("seen", set()):
            st.toast(f"✈️ New plane in range: {cs}")
    st.session_state.seen_key = key
    st.session_state.seen = current

    st.caption(f"{len(rows)} closest planes · last updated {time.strftime('%H:%M:%S')} (refreshes every 15 seconds)")
    if not rows:
        st.info("No planes with a known route in the sky within this radius right now.")
        return

    # 2) the list appears first
    df = pd.DataFrame(rows).sort_values("Distance (km)")
    render_table(df)

    # 3) the map loads after the list
    st.subheader("4. Where the planes are")
    st.caption("Flag = destination country. Hover a flag for details.")
    with st.spinner("🗺️ Loading map, please wait..."):
        render_plane_map(lat, lon, radius_km, df)


col_left, col_right = st.columns([2, 3], gap="large")

with col_left:
    st.subheader("1. Search or click to select location")
    with st.form("search_form", border=False):
        query = st.text_input(
            "Search a place",
            placeholder="Search a place, e.g. Tbilisi, NYC, London",
            label_visibility="collapsed",
        )
        searched = st.form_submit_button("🔍 Search")
    if searched and query.strip():
        found = geocode(query.strip())
        if found:
            st.session_state.loc = found
            st.session_state.center = list(found)
            st.session_state.zoom = 8
            st.rerun()
        else:
            st.warning("Place not found, try another name.")

    m = folium.Map(location=st.session_state.center, zoom_start=st.session_state.zoom)
    if st.session_state.loc:
        folium.Marker(st.session_state.loc, tooltip="Your location").add_to(m)
    out = st_folium(
        m,
        center=st.session_state.center,
        zoom=st.session_state.zoom,
        use_container_width=True,
        height=650,
        returned_objects=["last_clicked"],
    )

    st.subheader("2. Choose a radius")
    choice = st.segmented_control(
        "Radius",
        options=[25, 50, 100, 200, 300, 400],
        format_func=lambda x: f"{x} km",
        default=300,
        label_visibility="collapsed",
    )
    radius_km = choice or 300
    if st.session_state.loc:
        st.write(f"Selected point: {st.session_state.loc[0]:.4f}, {st.session_state.loc[1]:.4f}")

click = out.get("last_clicked") if out else None
if click:
    new = (click["lat"], click["lng"])
    if new != st.session_state.loc:
        st.session_state.loc = new
        st.rerun()

with col_right:
    st.subheader("3. Planes in the sky")
    if st.session_state.loc is None:
        st.info("Select a location on the map first.")
    else:
        lat, lon = st.session_state.loc
        show_flights(lat, lon, radius_km)