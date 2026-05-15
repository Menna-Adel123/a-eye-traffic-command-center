let incidents = [];
let selectedId = null;
let centerMode = 'map'; // 'map' or 'image/video'
let map, markers = {};
let isFetching = false;

// Authentication check
const token = localStorage.getItem('token');
const user = JSON.parse(localStorage.getItem('user'));
if (!token) {
  window.location.href = 'index.html';
}

// ===================== MAP =====================
function initMap() {
  map = L.map('mainMap', {
    center: [31.215, 29.955],
    zoom: 13,
    zoomControl: true,
  });

  L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
    attribution: '&copy; OpenStreetMap &copy; CARTO',
    maxZoom: 19,
  }).addTo(map);
}

function addMarker(inc) {
  if (markers[inc.incidentCode]) return; // Already exists
  const color = getSeverityColor(inc.severity);
  const icon = L.divIcon({
    className: 'custom-marker',
    html: `<div style="
      width:14px;height:14px;border-radius:50%;background:${color};
      border:2.5px solid white;box-shadow:0 2px 6px rgba(0,0,0,0.3);
      transition:transform 0.2s ease;
    " data-id="${inc.incidentCode}"></div>`,
    iconSize: [14, 14],
    iconAnchor: [7, 7],
  });

  const marker = L.marker([inc.latitude, inc.longitude], { icon }).addTo(map);
  marker.bindTooltip(`<strong>${inc.incidentCode}</strong><br>${inc.type} — ${inc.locationName}`, {
    direction: 'top', offset: [0, -10],
  });
  marker.on('click', () => selectIncident(inc.incidentCode));
  markers[inc.incidentCode] = marker;
}

function getSeverityColor(sev) {
  const colors = {
    high: '#E53935',
    medium: '#FFB300',
    low: '#16C79A'
  };
  return colors[sev] || '#9AA5B1';
}

function getSeverityLabel(sev) {
  return sev.charAt(0).toUpperCase() + sev.slice(1);
}

// ===================== EVENTS LIST =====================
function renderEvents() {
  const list = document.getElementById('eventsList');
  const count = document.getElementById('activeCount');
  if(count) count.textContent = incidents.length;
  
  list.innerHTML = incidents.map(inc => {
    const timeStr = new Date(inc.detectedAt).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'});
    return `
      <div class="event-card ${selectedId === inc.incidentCode ? 'selected' : ''}" onclick="selectIncident('${inc.incidentCode}')" data-id="${inc.incidentCode}">
        <div class="severity-stripe" style="background:${getSeverityColor(inc.severity)}"></div>
        <div class="event-card-content">
          <div class="event-code">${inc.incidentCode} <span style="float:right; font-size: 11px; padding: 2px 6px; border-radius: 4px; background: #eee">${inc.status}</span></div>
          <div class="event-label">${inc.type} — <span style="color:${getSeverityColor(inc.severity)};font-weight:600">${getSeverityLabel(inc.severity)}</span></div>
          <div class="event-meta">${timeStr} — ${inc.locationName}</div>
        </div>
      </div>
    `;
  }).join('');
}

// ===================== SELECT INCIDENT =====================
function selectIncident(id) {
  selectedId = id;
  const inc = incidents.find(i => i.incidentCode === id);
  if (!inc) return;

  renderEvents(); // Update highlighting

  // Zoom map
  if (map) {
    map.flyTo([inc.latitude, inc.longitude], 15, { duration: 0.8 });
    Object.entries(markers).forEach(([mId, m]) => {
      const el = m.getElement();
      if (el) {
        const dot = el.querySelector('div');
        if (dot) {
          dot.style.transform = mId === id ? 'scale(1.6)' : 'scale(1)';
          dot.style.zIndex = mId === id ? '1000' : '1';
        }
      }
    });
  }

  if (centerMode === 'image') switchCenter('map');
  renderRightPanel(inc);
}

// ===================== CENTER SWITCH =====================
function switchCenter(mode) {
  centerMode = mode;
  const mapView = document.getElementById('mapView');
  const imageView = document.getElementById('imageView');

  if (mode === 'map') {
    mapView.classList.remove('hidden');
    mapView.classList.add('visible');
    imageView.classList.remove('visible');
    imageView.classList.add('hidden');
    setTimeout(() => map && map.invalidateSize(), 400);
  } else {
    imageView.classList.remove('hidden');
    imageView.classList.add('visible');
    mapView.classList.remove('visible');
    mapView.classList.add('hidden');
    
    // update center view media
    if (selectedId) {
      const inc = incidents.find(i => i.incidentCode === selectedId);
      if (inc) {
        const mediaHtml = inc.videoUrl 
          ? `<video src="${inc.videoUrl}" style="width:100%;height:100%;object-fit:cover;display:block;" controls autoplay muted loop onerror="this.outerHTML='<div class=\'camera-feed-placeholder\'><i class=\'fa-solid fa-video-slash\' style=\'font-size:32px;opacity:0.3\'></i><span>Video Unavailable</span></div>'"></video>`
          : `<div class="camera-feed-placeholder" style="height:100%;"><i class="fa-solid fa-video-slash" style="font-size:32px;opacity:0.3"></i><span style="font-size:13px;opacity:0.5;font-weight:600;">Incident Video Unavailable</span></div>`;
        document.getElementById('centerImage').innerHTML = mediaHtml;
      }
    }
  }

  if (selectedId) {
    const inc = incidents.find(i => i.incidentCode === selectedId);
    if (inc) renderRightPanel(inc);
  }
}

// ===================== RIGHT PANEL =====================
function renderRightPanel(inc) {
  const container = document.getElementById('rightContent');
  const showMapThumb = centerMode === 'image';
  const thumbLabel = showMapThumb ? 'View Map' : 'View Camera Feed';
  
  const timeStr = new Date(inc.detectedAt).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'});
  const dateStr = new Date(inc.detectedAt).toLocaleDateString();
  
  const mediaHtml = inc.videoUrl 
          ? `<video src="${inc.videoUrl}" style="width:100%;height:100%;object-fit:cover;display:block;" autoplay muted loop onerror="this.parentElement.innerHTML='<div style=\'height:100%;display:flex;align-items:center;justify-content:center;background:#1a1e2a;color:rgba(255,255,255,0.2)\'><i class=\'fa-solid fa-video-slash\'></i></div>'"></video>`
          : `<div style="height:100%;display:flex;align-items:center;justify-content:center;background:#1a1e2a;color:rgba(255,255,255,0.2)"><i class="fa-solid fa-video-slash"></i></div>`;

  container.innerHTML = `
    <!-- Thumbnail -->
    <div class="right-section">
      <div class="right-section-title">${showMapThumb ? 'Map View' : 'Camera Recording'}</div>
      <div class="thumbnail-card" onclick="switchCenter('${showMapThumb ? 'map' : 'image'}')" style="position:relative;overflow:hidden;">
        ${showMapThumb ? '' : mediaHtml}
      
        ${showMapThumb ? `
          <div class="thumbnail-mini-map" style="background:#e8ecf1;display:flex;align-items:center;justify-content:center;height:100%">
            <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="var(--text-muted)" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
              <polygon points="1 6 1 22 8 18 16 22 23 18 23 2 16 6 8 2 1 6"/>
              <line x1="8" y1="2" x2="8" y2="18"/>
              <line x1="16" y1="6" x2="16" y2="22"/>
            </svg>
          </div>
        ` : `
          <div class="thumbnail-camera" style="position:absolute;top:0;left:0;right:0;bottom:0;pointer-events:none;z-index:10;">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="rgba(255,255,255,0.7)" stroke-width="1.5" style="margin:10px;">
              <path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/>
              <circle cx="12" cy="13" r="4"/>
            </svg>
          </div>
        `}
        <div class="thumb-overlay" style="position:absolute;bottom:0;width:100%;background:rgba(0,0,0,0.5);color:white;text-align:center;padding:4px 0;z-index:11;">
          <span class="thumb-overlay-label">${thumbLabel}</span>
        </div>
      </div>
    </div>

    <!-- Incident Details -->
    <div class="right-section">
      <div class="right-section-title">Incident Details</div>
      <div>
        <div class="detail-row">
          <span class="detail-label">Incident</span>
          <span class="detail-value" style="font-weight:600">${inc.incidentCode}</span>
        </div>
        <div class="detail-row">
          <span class="detail-label">Status</span>
          <span class="detail-value" style="text-transform:uppercase;font-weight:bold">${inc.status}</span>
        </div>
        <div class="detail-row">
          <span class="detail-label">Type</span>
          <span class="detail-value">${inc.type}</span>
        </div>
        <div class="detail-row">
          <span class="detail-label">Location</span>
          <span class="detail-value">${inc.camera} — ${inc.locationName}</span>
        </div>
        <div class="detail-row">
          <span class="detail-label">Date</span>
          <span class="detail-value">${dateStr}</span>
        </div>
        <div class="detail-row">
          <span class="detail-label">Time</span>
          <span class="detail-value">${timeStr}</span>
        </div>
        <div class="detail-row">
          <span class="detail-label">Severity</span>
          <span class="badge badge-${inc.severity}">
            <span class="severity-dot ${inc.severity}"></span>
            ${getSeverityLabel(inc.severity)}
          </span>
        </div>
        <div class="detail-row" style="flex-direction:column;align-items:stretch;gap:6px">
          <span class="detail-label">AI Confidence</span>
          <div class="confidence-bar">
            <div class="confidence-track">
              <div class="confidence-fill" style="width:${inc.confidence}%"></div>
            </div>
            <span class="confidence-value">${inc.confidence}%</span>
          </div>
        </div>
      </div>
    </div>
  `;

  // Actions
  const existing = document.querySelector('.action-buttons');
  if (existing) existing.remove();

  if (inc.status === 'pending') {
    const actions = document.createElement('div');
    actions.className = 'action-buttons';
    actions.innerHTML = `
      <button class="btn btn-danger btn-full" onclick="handleAction('${inc.incidentCode}', 'dispatch')">
        Dispatch
      </button>
      <button class="btn btn-navy btn-full" onclick="handleAction('${inc.incidentCode}', 'traffic-unit')">
        Send Traffic Unit
      </button>
      <button class="btn btn-grey btn-full" onclick="handleAction('${inc.incidentCode}', 'false-alert')">
        Mark as False Alert
      </button>
    `;
    document.getElementById('rightPanel').appendChild(actions);
  }
}

async function handleAction(id, action) {
  // Create modal overlay
  const overlay = document.createElement('div');
  overlay.className = 'action-modal-overlay';
  overlay.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(13,27,42,0.8);z-index:9999;display:flex;align-items:center;justify-content:center;backdrop-filter:blur(4px);opacity:0;transition:opacity 0.2s ease;';
  
  const title = action === 'dispatch' ? 'Dispatch Ambulance' : action === 'traffic-unit' ? 'Send Traffic Unit' : 'Mark False Alert';
  const showVehicle = action !== 'false-alert';

  const modalHtml = `
    <div class="action-modal card card-padded" style="width:100%;max-width:400px;transform:scale(0.95);transition:transform 0.2s ease;">
      <h3 style="margin-bottom:16px;">${title}</h3>
      ${showVehicle ? `
        <div class="form-group" style="margin-bottom:12px;">
          <label class="form-label">Vehicle ID / License Plate (Optional)</label>
          <input type="text" id="modalVehicleId" class="form-input" placeholder="e.g. ABC-1234">
        </div>
      ` : ''}
      <div class="form-group" style="margin-bottom:12px;">
        <label class="form-label">Severity Override</label>
        <select id="modalSeverity" class="form-input">
          <option value="">Keep Original</option>
          <option value="high">High</option>
          <option value="medium">Medium</option>
          <option value="low">Low</option>
        </select>
      </div>
      <div class="form-group" style="margin-bottom:20px;">
        <label class="form-label">Review Notes (Optional)</label>
        <textarea id="modalNotes" class="form-input" rows="3" placeholder="Add any details..."></textarea>
      </div>
      <div style="display:flex;gap:12px;justify-content:flex-end;">
        <button class="btn btn-grey" id="modalCancel">Cancel</button>
        <button class="btn btn-primary" id="modalSubmit">Confirm</button>
      </div>
    </div>
  `;
  overlay.innerHTML = modalHtml;
  document.body.appendChild(overlay);

  // Animate in
  requestAnimationFrame(() => {
    overlay.style.opacity = '1';
    overlay.querySelector('.action-modal').style.transform = 'scale(1)';
  });

  return new Promise((resolve) => {
    const close = () => {
      overlay.style.opacity = '0';
      overlay.querySelector('.action-modal').style.transform = 'scale(0.95)';
      setTimeout(() => overlay.remove(), 200);
      resolve();
    };

    document.getElementById('modalCancel').onclick = close;
    document.getElementById('modalSubmit').onclick = async () => {
      const reviewNotes = document.getElementById('modalNotes').value;
      const severity = document.getElementById('modalSeverity').value || undefined;
      const vehicleId = showVehicle ? document.getElementById('modalVehicleId').value : undefined;
      
      const payload = { reviewNotes };
      if (severity) payload.severity = severity;
      if (vehicleId) payload.vehicleId = vehicleId;

      const submitBtn = document.getElementById('modalSubmit');
      submitBtn.textContent = 'Sending...';
      submitBtn.disabled = true;

      try {
        const res = await fetch(`/api/incidents/${id}/${action}`, {
          method: 'PATCH',
          headers: { 
            'Authorization': `Bearer ${token}`,
            'Content-Type': 'application/json'
          },
          body: JSON.stringify(payload)
        });
        if (res.ok) {
          console.log(`Action ${action} executed for ${id}`);
          close();
        } else {
          alert('Failed to execute action');
          submitBtn.textContent = 'Confirm';
          submitBtn.disabled = false;
        }
      } catch (err) {
        console.error(err);
        alert('Server connection error');
        submitBtn.textContent = 'Confirm';
        submitBtn.disabled = false;
      }
    };
  });
}

// ===================== DATA & POLLING =====================
async function fetchIncidents() {
  if (isFetching) return;
  isFetching = true;
  try {
    const res = await fetch('/api/incidents?status=pending,emergency', {
      headers: { 'Authorization': `Bearer ${token}` }
    });
    if (res.ok) {
      const data = await res.json();
      
      // Update logic without sockets
      const newIncidents = data.incidents || [];
      
      // Find incidents that were removed/resolved
      const newIds = newIncidents.map(i => i.incidentCode);
      incidents.forEach((inc, index) => {
        if (!newIds.includes(inc.incidentCode)) {
          if (markers[inc.incidentCode]) {
            map.removeLayer(markers[inc.incidentCode]);
            delete markers[inc.incidentCode];
          }
          if (selectedId === inc.incidentCode) {
            selectedId = null;
            document.getElementById('rightContent').innerHTML = `
              <div class="no-selection">
                <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
                  <circle cx="12" cy="12" r="10"/>
                  <line x1="12" y1="8" x2="12" y2="12"/>
                  <line x1="12" y1="16" x2="12.01" y2="16"/>
                </svg>
                <div style="font-size:14px;font-weight:500;color:var(--text-secondary)">No Incident Selected</div>
                <div style="font-size:12px">Click an event from the left panel</div>
              </div>`;
          }
        }
      });
      
      // Add or update incidents
      newIncidents.forEach(newInc => {
        const existingIndex = incidents.findIndex(i => i.incidentCode === newInc.incidentCode);
        if (existingIndex === -1) {
          addMarker(newInc); // New incident
        } else {
          // Check if data changed
          const existing = incidents[existingIndex];
          if (existing.status !== newInc.status || existing.severity !== newInc.severity) {
             if (selectedId === newInc.incidentCode) {
                renderRightPanel(newInc);
             }
          }
        }
      });
      
      incidents = newIncidents;
      renderEvents();
    } else {
      if (res.status === 401) {
        localStorage.clear();
        window.location.href = 'index.html';
      }
    }
  } catch (error) {
    console.error('Failed to fetch incidents', error);
  } finally {
    isFetching = false;
  }
}



// ===================== UI INITIALIZATION =====================
function initProfile() {
  if (user) {
    const nameEl = document.querySelector('.officer-name');
    const roleEl = document.querySelector('.officer-role');
    const avatarEl = document.querySelector('.officer-avatar');
    if (nameEl) nameEl.textContent = user.name;
    if (roleEl) roleEl.textContent = user.role;
    if (avatarEl && user.name) {
      avatarEl.textContent = user.name.split(' ').map(n => n[0]).join('').substring(0, 2).toUpperCase();
    }

    // Show 'Add User' button if admin
    if (user.role === 'admin') {
      const addBtn = document.getElementById('createUserBtn');
      if (addBtn) {
        addBtn.style.display = 'inline-block';
        addBtn.addEventListener('click', (e) => {
          e.preventDefault();
          showCreateUserModal();
        });
      }
    }
  }
}

// Run profile init immediately
initProfile();

// ===================== INIT =====================
document.addEventListener('DOMContentLoaded', () => {
  initMap();
  fetchIncidents();
  // Poll for incidents every 3 seconds
  setInterval(fetchIncidents, 3000);
});

// ===================== ADMIN: CREATE USER =====================
function showCreateUserModal() {
  const overlay = document.createElement('div');
  overlay.className = 'action-modal-overlay';
  overlay.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(13,27,42,0.8);z-index:9999;display:flex;align-items:center;justify-content:center;backdrop-filter:blur(4px);opacity:0;transition:opacity 0.2s ease;';
  
  const modalHtml = `
    <div class="action-modal card card-padded" style="width:100%;max-width:400px;transform:scale(0.95);transition:transform 0.2s ease;">
      <h3 style="margin-bottom:16px;">Create New User</h3>
      <div class="form-group" style="margin-bottom:12px;">
        <label class="form-label">Full Name</label>
        <input type="text" id="cuName" class="form-input" placeholder="e.g. Jane Doe">
      </div>
      <div class="form-group" style="margin-bottom:12px;">
        <label class="form-label">Email Address</label>
        <input type="email" id="cuEmail" class="form-input" placeholder="jane.doe@example.com">
      </div>
      <div class="form-group" style="margin-bottom:12px;">
        <label class="form-label">Role</label>
        <select id="cuRole" class="form-input">
          <option value="officer">Officer</option>
          <option value="admin">Admin</option>
        </select>
      </div>
      <div class="form-group" style="margin-bottom:20px;">
        <label class="form-label">Station (Optional)</label>
        <input type="text" id="cuStation" class="form-input" placeholder="e.g. North District">
      </div>
      <div style="display:flex;gap:12px;justify-content:flex-end;">
        <button class="btn btn-grey" id="cuCancel">Cancel</button>
        <button class="btn btn-primary" id="cuSubmit">Create User</button>
      </div>
    </div>
  `;
  overlay.innerHTML = modalHtml;
  document.body.appendChild(overlay);

  requestAnimationFrame(() => {
    overlay.style.opacity = '1';
    overlay.querySelector('.action-modal').style.transform = 'scale(1)';
  });

  const close = () => {
    overlay.style.opacity = '0';
    overlay.querySelector('.action-modal').style.transform = 'scale(0.95)';
    setTimeout(() => overlay.remove(), 200);
  };

  document.getElementById('cuCancel').onclick = close;
  document.getElementById('cuSubmit').onclick = async () => {
    const name = document.getElementById('cuName').value.trim();
    const email = document.getElementById('cuEmail').value.trim();
    const role = document.getElementById('cuRole').value;
    const station = document.getElementById('cuStation').value.trim();

    if (!name || !email) return alert('Name and Email are required.');

    const submitBtn = document.getElementById('cuSubmit');
    submitBtn.textContent = 'Creating...';
    submitBtn.disabled = true;

    try {
      const res = await fetch('/api/auth/create-user', {
        method: 'POST',
        headers: { 
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ name, email, role, station })
      });
      
      const data = await res.json();
      if (res.ok) {
        alert('User created successfully.\\nCredentials have been emailed to: ' + email);
        close();
      } else {
        alert('Error: ' + (data.error || 'Failed to create user'));
        submitBtn.textContent = 'Create User';
        submitBtn.disabled = false;
      }
    } catch (err) {
      console.error(err);
      alert('Server connection error');
      submitBtn.textContent = 'Create User';
      submitBtn.disabled = false;
    }
  };
}

// ===================== LOGOUT =====================
async function handleLogout() {
  try {
    await fetch('/api/auth/logout', {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${token}` }
    });
  } catch (error) {
    console.warn('Logout error:', error);
  } finally {
    localStorage.clear();
    window.location.href = 'index.html';
  }
}