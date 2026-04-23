import os
import re

with open("routes/scanner.py", "r", encoding="utf-8") as f:
    content = f.read()

helper_funcs = """

def haversine(lat1, lon1, lat2, lon2):
    import math
    R = 6371000
    phi1 = math.radians(float(lat1))
    phi2 = math.radians(float(lat2))
    delta_phi = math.radians(float(lat2) - float(lat1))
    delta_lambda = math.radians(float(lon2) - float(lon1))
    a = math.sin(delta_phi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
    return R * (2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)))

def get_search_points(lat, lng, radius_m):
    import math
    lat = float(lat)
    lng = float(lng)
    radius_m = int(radius_m)
    points = [{"lat": lat, "lng": lng}]
    if radius_m <= 2000:
        return points
    offset_m = radius_m * 0.6
    lat_offset = offset_m / 111320.0
    lng_offset = offset_m / (111320.0 * math.cos(math.radians(lat)))
    points.append({"lat": lat + lat_offset, "lng": lng})
    points.append({"lat": lat - lat_offset, "lng": lng})
    points.append({"lat": lat, "lng": lng + lng_offset})
    points.append({"lat": lat, "lng": lng - lng_offset})
    if radius_m >= 10000:
        points.append({"lat": lat + lat_offset*0.7, "lng": lng + lng_offset*0.7})
        points.append({"lat": lat - lat_offset*0.7, "lng": lng - lng_offset*0.7})
        points.append({"lat": lat + lat_offset*0.7, "lng": lng - lng_offset*0.7})
        points.append({"lat": lat - lat_offset*0.7, "lng": lng + lng_offset*0.7})
    return points

"""

if "def get_search_points(" not in content:
    content = content.replace("import base64", "import base64\n" + helper_funcs)

def replacer(match):
    block = match.group(0)
    
    # Extract the ignore logic from the block
    ignore_logic_match = re.search(r'(ignore_keywords\s*=\s*\[.*?\])', block, re.DOTALL)
    ignore_logic = ignore_logic_match.group(1) if ignore_logic_match else ""
    
    if ignore_logic:
        condition = f"not any(k in p_name for k in ignore_keywords)"
    else:
        condition = "True"
        
    custom_loop = f"""
        search_points = get_search_points(y, x, radius)
        
        import concurrent.futures
        def fetch_kw(pt, kw):
            try:
                import urllib.parse, requests
                r_val = int(radius)//2 if int(radius) > 3000 else radius
                k_url = f"https://dapi.kakao.com/v2/local/search/keyword.json?query={{urllib.parse.quote(kw)}}&x={{pt['lng']}}&y={{pt['lat']}}&radius={{r_val}}&page=1"
                return requests.get(k_url, headers=headers, timeout=3).json().get('documents', [])
            except:
                return []
                
        futures = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            for pt in search_points:
                for kw in keywords:
                    futures.append(executor.submit(fetch_kw, pt, kw))
                    
        {ignore_logic}
        
        for future in concurrent.futures.as_completed(futures):
            docs = future.result()
            for d in docs:
                p_name = d.get('place_name', '')
                try:
                    d_lat = float(d.get('y', 0))
                    d_lng = float(d.get('x', 0))
                    actual_dist = haversine(float(y), float(x), d_lat, d_lng)
                    d['distance'] = str(int(actual_dist))
                    
                    if actual_dist <= int(radius) and d['id'] not in seen_ids and {condition}:
                        places.append(d)
                        seen_ids.add(d['id'])
                except Exception as e:
                    pass
"""
    # Fix the indentation of custom_loop to match the '        for kw in keywords:' level
    return custom_loop

pattern = re.compile(r'        for kw in keywords:.*?seen_ids\.add\(d\[\'id\'\]\)', re.DOTALL)
content = pattern.sub(replacer, content)

with open("routes/scanner.py", "w", encoding="utf-8") as f:
    f.write(content)

print("Radius perimeter search logic injected safely!")
