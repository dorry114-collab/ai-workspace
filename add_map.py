import re

files = [
    'templates/restaurant.html',
    'templates/bakery.html',
    'templates/cafe.html',
    'templates/clinic.html'
]

map_html = """
        <div id="mapContainer" style="width: 100%; height: 350px; border-radius: 16px; margin-bottom: 2rem; border: 1px solid var(--border-color); display: none; overflow: hidden; box-shadow: 0 10px 30px rgba(0,0,0,0.5);"></div>
"""

map_js = """
        let map;
        let markers = [];
        let infoWindow;

        function initMap() {
            // Callback for Google Maps
        }

        function updateMap(centerData, filteredData) {
            if (!document.getElementById('mapContainer')) return;
            
            if (typeof google === 'undefined' || !google.maps) {
                return; // Maps API not loaded
            }
            
            document.getElementById('mapContainer').style.display = 'block';
            
            if (!map) {
                map = new google.maps.Map(document.getElementById('mapContainer'), {
                    zoom: 14,
                    center: { lat: parseFloat(centerData.y), lng: parseFloat(centerData.x) },
                    styles: [
                        { elementType: "geometry", stylers: [{ color: "#242f3e" }] },
                        { elementType: "labels.text.stroke", stylers: [{ color: "#242f3e" }] },
                        { elementType: "labels.text.fill", stylers: [{ color: "#746855" }] },
                        { featureType: "water", elementType: "geometry", stylers: [{ color: "#17263c" }] }
                    ],
                    disableDefaultUI: true,
                    zoomControl: true
                });
                infoWindow = new google.maps.InfoWindow();
            } else {
                map.setCenter({ lat: parseFloat(centerData.y), lng: parseFloat(centerData.x) });
            }
            
            // Clear markers
            markers.forEach(m => m.setMap(null));
            markers = [];
            
            // Add new markers
            filteredData.forEach(r => {
                if(r.y && r.x) {
                    const marker = new google.maps.Marker({
                        position: { lat: parseFloat(r.y), lng: parseFloat(r.x) },
                        map: map,
                        title: r.name,
                        animation: google.maps.Animation.DROP
                    });
                    
                    marker.addListener('click', () => {
                        infoWindow.setContent(`<div style="color: black; font-weight: bold; padding: 5px;">${r.name}</div><div style="color: #666; font-size: 0.8rem; padding: 0 5px 5px 5px;">${r.category}</div>`);
                        infoWindow.open(map, marker);
                        
                        // Scroll to card
                        const card = document.getElementById('card-' + r.place_id);
                        if(card) {
                            card.scrollIntoView({ behavior: 'smooth', block: 'center' });
                            card.style.boxShadow = '0 0 20px var(--primary)';
                            setTimeout(() => { card.style.boxShadow = ''; }, 2000);
                        }
                    });
                    markers.push(marker);
                }
            });
        }
"""

for filepath in files:
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()

        # 1. Add script tag if not exists
        if 'maps.googleapis.com' not in content:
            script_tag = '{% if google_maps_api_key %}\n    <script src="https://maps.googleapis.com/maps/api/js?key={{ google_maps_api_key }}&callback=initMap" async defer></script>\n    {% endif %}'
            content = content.replace('</head>', script_tag + '\n</head>')

        # 2. Add Map Container before <div class="controls-area"
        if 'id="mapContainer"' not in content:
            content = content.replace('<div class="controls-area"', map_html + '\n        <div class="controls-area"')

        # 3. Inject Map JS
        if 'let map;' not in content:
            content = content.replace('let allRestaurants = [];', 'let allRestaurants = [];\n        let currentCenter = null;\n' + map_js)

        # 4. In performSearch, save the center
        # Find: allRestaurants = data.data;
        if 'currentCenter = data.center;' not in content:
            content = content.replace('allRestaurants = data.data;', 'allRestaurants = data.data;\n                if(data.center) currentCenter = data.center;')

        # 5. In renderCards, call updateMap
        # Find: grid.appendChild(card); \n            });
        if 'updateMap(currentCenter, filtered);' not in content:
            content = content.replace('grid.appendChild(card);\n            });', 'grid.appendChild(card);\n            });\n            if(currentCenter) updateMap(currentCenter, filtered);')

        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
            
        print(f"Updated {filepath}")
    except Exception as e:
        print(f"Failed {filepath}: {e}")

