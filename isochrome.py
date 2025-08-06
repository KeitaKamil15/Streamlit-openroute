import os
import json
import time
import folium
import geopandas as gpd
import openrouteservice
import streamlit as st
from shapely.geometry import shape
from streamlit_folium import st_folium

COLOR_MAP = {
    "driving-traffic": "#377eb8",
    "driving-car": "#1a9641",
    "cycling-regular": "#fdae61",
    "foot-walking": "#2b83ba",
    "driving-hgv": "#a6d96a",
    "cycling-electric": "#d7191c",
    "foot-hiking": "#984ea3",
    "wheelchair": "#ff7f00"
}

class IsochroneAnalyzer:
    def __init__(self, api_key, file_kml, list_menit, profile_list, sampling_interval=20):
        self.api_key = api_key
        self.file_kml = file_kml
        self.list_menit = list_menit
        self.sampling_interval = sampling_interval
        self.client = openrouteservice.Client(key=api_key)
        self.profile_list = profile_list
        self.range_detik = list_menit
        self.gdf_kml = None
        self.centroid = None
        self.koordinat_list = []
        self.map = None
        self.area_summary = []

    def retry_request(self, func, max_retries=3, wait=5):
        for attempt in range(max_retries):
            try:
                return func()
            except openrouteservice.exceptions.ApiError as e:
                st.warning(f"⚠️ Rate limit: mencoba ulang ke-{attempt+1} dalam {wait} detik...")
                time.sleep(wait)
        raise RuntimeError("❌ Gagal setelah beberapa kali mencoba ulang.")

    def load_kml(self):
        gdf_kml = gpd.read_file(self.file_kml, driver='KML')
        if gdf_kml.empty:
            st.error("File KML kosong atau tidak valid.")
            return False

        self.gdf_kml = gdf_kml
        self.centroid = gdf_kml.geometry.union_all().centroid

        boundary_points = []
        for geom in gdf_kml.geometry:
            if geom.geom_type == "Polygon":
                boundary_points.extend(list(geom.exterior.coords))
            elif geom.geom_type == "MultiPolygon":
                for poly in geom.geoms:
                    boundary_points.extend(list(poly.exterior.coords))

        self.koordinat_list = [[point[0], point[1]] for point in boundary_points][::self.sampling_interval]
        st.info(f"📍 Menggunakan {len(self.koordinat_list)} titik dari batas polygon KML")
        return True

    def build_map(self):
        m = folium.Map(location=[self.centroid.y, self.centroid.x], zoom_start=13, control_scale=True)

        folium.GeoJson(
            self.gdf_kml,
            name="Wilayah Asli (KML)",
            style_function=lambda feature: {
                'fillColor': '#ffc0cb',
                'color': '#ff69b4',
                'weight': 2,
                'fillOpacity': 1.0
            },
            tooltip="Polygon Asli dari KML"
        ).add_to(m)

        bounds = self.gdf_kml.total_bounds
        m.fit_bounds([[bounds[1], bounds[0]], [bounds[3], bounds[2]]])

        self.map = m

    def generate_isochrones(self):
        for profile in self.profile_list:
            st.write(f"🔄 Mengambil isochrone untuk: {profile}")
            warna_fill = COLOR_MAP.get(profile, "#666666")
            total_area_m2 = 0

            for idx, koordinat in enumerate(self.koordinat_list):
                try:
                    isochrones = self.retry_request(lambda: self.client.isochrones(
                        locations=[koordinat],
                        profile=profile,
                        range=converted_range,
                        attributes=["area"],
                        **({"options": {"traffic": True}} if profile == "driving-traffic" else {})
                    ))

                    for feature in isochrones["features"]:
                        waktu = feature['properties']['value'] // 60
                        area_m2 = feature["properties"].get("area", 0)
                        total_area_m2 += area_m2

                        folium.GeoJson(
                            feature,
                            name=f"{waktu} menit - {profile}",
                            style_function=lambda feature, clr=warna_fill: {
                                'fillColor': clr,
                                'color': clr,
                                'weight': 1,
                                'fillOpacity': 0.2
                            },
                            tooltip=f"{waktu} menit - {profile} ({round(area_m2/1e6, 2)} km²)"
                        ).add_to(self.map)

                    time.sleep(2.5)
                except Exception as e:
                    st.error(f"❌ Gagal untuk titik ke-{idx}: {e}")
                    continue

            self.area_summary.append({
                "profile": profile,
                "total_area_km2": round(total_area_m2 / 1e6, 2)
            })

        folium.Marker(location=[self.centroid.y, self.centroid.x], tooltip="Titik Pusat").add_to(self.map)
        folium.LayerControl(collapsed=False).add_to(self.map)

    def display_summary(self):
        st.subheader("📊 Ringkasan Area")
        for item in self.area_summary:
            st.markdown(f"- **{item['profile']}**: {item['total_area_km2']} km²")

    def show_map(self):
        st_folium(self.map, width=725, height=500)

# Streamlit UI
input_type = st.radio("Pilih jenis input:", ["File KML", "Titik Koordinat"])

file_kml = None
coordinate_input = None
if input_type == "File KML":
    file_kml = st.file_uploader("Unggah file .KML", type="kml")
elif input_type == "Titik Koordinat":
    coordinate_input = st.text_input("Masukkan koordinat (format: lon,lat):")
st.set_page_config(page_title="Isochrone KML", layout="centered")
st.title("🗺️ Isochrone Map dari File KML")

api_key = st.text_input("Masukkan OpenRouteService API Key:", type="password")
range_type = st.radio("Pilih tipe jangkauan:", ["Waktu (menit)", "Jarak (meter)"])
if range_type == "Waktu (menit)":
    nilai_range = st.multiselect("Pilih waktu isochrone (menit):", [5, 10, 15, 20, 25, 30], default=[5, 10, 15])
    converted_range = [r * 60 for r in nilai_range]  # detik
else:
    nilai_range = st.multiselect("Pilih jarak isochrone (meter):", [500, 1000, 1500, 2000, 2500, 3000], default=[1000, 2000])
    converted_range = nilai_range
profile_list = st.multiselect("Pilih profil perjalanan:", list(COLOR_MAP.keys()), default=["driving-car", "cycling-regular", "foot-walking"])
sampling = st.slider("Sampling Titik (semakin besar semakin ringan):", min_value=5, max_value=50, value=20, step=5)

# Inisialisasi state sebelum tombol dijalankan
if 'run_analysis' not in st.session_state:
    st.session_state.run_analysis = False

if api_key and ((input_type == "File KML" and file_kml) or (input_type == "Titik Koordinat" and coordinate_input)) and nilai_range and profile_list:
    if 'run_analysis' not in st.session_state:
        st.session_state.run_analysis = False

if st.button("🚀 Jalankan Analisis"):
    st.session_state.run_analysis = True

if st.session_state.run_analysis:
        if input_type == "File KML":
            path_kml = os.path.join("temp_uploaded.kml")
            with open(path_kml, "wb") as f:
                f.write(file_kml.read())
            
        elif input_type == "Titik Koordinat":
            try:
                lon, lat = map(float, coordinate_input.split(","))
                centroid = gpd.points_from_xy([lon], [lat])[0]
                m = folium.Map(location=[lat, lon], zoom_start=13, control_scale=True)
                client = openrouteservice.Client(key=api_key)
                range_detik = converted_range
                area_summary = []

                for profile in profile_list:
                    st.write(f"🔄 Mengambil isochrone untuk: {profile}")
                    warna_fill = COLOR_MAP.get(profile, "#666666")
                    total_area_m2 = 0

                    analyzer = IsochroneAnalyzer(api_key, None, converted_range, profile_list)
                    isochrones = analyzer.retry_request(lambda: client.isochrones(
                        locations=[[lon, lat]],
                        profile=profile,
                        range=converted_range,
                        attributes=["area"],
                        options={"traffic": True} if profile == "driving-traffic" else None
                    ))

                    for feature in isochrones["features"]:
                        waktu = feature['properties']['value'] // 60
                        area_m2 = feature["properties"].get("area", 0)
                        total_area_m2 += area_m2

                        folium.GeoJson(
                            feature,
                            name=f"{waktu} menit - {profile}",
                            style_function=lambda feature, clr=warna_fill: {
                                'fillColor': clr,
                                'color': clr,
                                'weight': 1,
                                'fillOpacity': 0.4
                            },
                            tooltip=f"{waktu} menit - {profile} ({round(area_m2/1e6, 2)} km²)"
                        ).add_to(m)

                    area_summary.append({
                        "profile": profile,
                        "total_area_km2": round(total_area_m2 / 1e6, 2)
                    })

                folium.Marker(location=[lat, lon], tooltip="Titik Input").add_to(m)
                folium.LayerControl(collapsed=False).add_to(m)

                st.subheader("📊 Ringkasan Area")
                for item in area_summary:
                    st.markdown(f"- **{item['profile']}**: {item['total_area_km2']} km²")

                st_folium(m, width=725, height=500)
            except Exception as e:
                st.error(f"❌ Format koordinat salah atau error saat proses: {e}")

        analyzer = IsochroneAnalyzer(api_key, path_kml, converted_range, profile_list, sampling_interval=sampling)
        if analyzer.load_kml():
                analyzer.build_map()
                analyzer.generate_isochrones()
                analyzer.display_summary()
                analyzer.show_map()
