let tableData = [];

// Authentication check
const token = localStorage.getItem('token');
const user = JSON.parse(localStorage.getItem('user'));
if (!token) {
  window.location.href = 'index.html';
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

initProfile();

document.addEventListener('DOMContentLoaded', () => {
  // Set default dates (Last 30 days)
  const today = new Date();
  const thirtyDaysAgo = new Date();
  thirtyDaysAgo.setDate(today.getDate() - 30);
  
  const formatDate = (d) => {
    const year = d.getFullYear();
    const month = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
  };

  document.getElementById('dateFrom').value = formatDate(thirtyDaysAgo);
  document.getElementById('dateTo').value = formatDate(today);

  fetchAnalytics();

  // Add filter listeners
  document.querySelector('.filter-btn').addEventListener('click', applyFilters);
});

async function fetchAnalytics() {
  try {
    const res = await fetch('/api/incidents', {
      headers: { 'Authorization': `Bearer ${token}` }
    });
    if (res.ok) {
      const data = await res.json();
      tableData = data.incidents || [];
      populateFilters(tableData);
      calculateKPIs(tableData);
      renderTable(tableData);
    } else {
      if (res.status === 401) {
        localStorage.clear();
        window.location.href = 'index.html';
      }
    }
  } catch (error) {
    console.error('Failed to fetch analytics', error);
  }
}

function populateFilters(data) {
  const areas = [...new Set(data.map(i => i.locationName))].sort();
  const cameras = [...new Set(data.map(i => i.camera))].sort();

  const areaSelect = document.querySelectorAll('.filter-select')[0];
  const cameraSelect = document.querySelectorAll('.filter-select')[1];

  areaSelect.innerHTML = '<option>All Areas</option>' + areas.map(a => `<option>${a}</option>`).join('');
  cameraSelect.innerHTML = '<option>All Cameras</option>' + cameras.map(c => `<option>${c}</option>`).join('');
}

function calculateKPIs(data) {
  const total = data.length;
  const highSev = data.filter(i => i.severity === 'high').length;
  const falseAlerts = data.filter(i => i.status === 'false-alert').length;
  const trueAlerts = data.filter(i => i.status !== 'false-alert' && i.status !== 'pending').length;
  const trueAlertRate = total ? Math.round(( (total - falseAlerts) / total) * 100) : 0;
  
  const responseTimes = data.filter(i => i.responseTimeMins).map(i => i.responseTimeMins);
  const avgResponse = responseTimes.length 
    ? (responseTimes.reduce((a, b) => a + b, 0) / responseTimes.length).toFixed(1)
    : '0.0';

  // Update DOM
  const kpiTotal = document.querySelector('.kpi-total .kpi-value');
  const kpiHigh = document.querySelector('.kpi-high .kpi-value');
  const kpiAlerts = document.querySelector('.kpi-alerts .kpi-value');
  const kpiAlertsSub = document.querySelector('.kpi-alerts .kpi-sub');
  const kpiResponse = document.querySelector('.kpi-response .kpi-value');
  const tableCount = document.querySelector('.table-count');

  if (kpiTotal) kpiTotal.textContent = total;
  if (kpiHigh) kpiHigh.textContent = highSev;
  if (kpiAlerts) kpiAlerts.textContent = `${total - falseAlerts} / ${falseAlerts}`;
  if (kpiAlertsSub) kpiAlertsSub.textContent = `${trueAlertRate}% true alert rate`;
  if (kpiResponse) kpiResponse.innerHTML = `${avgResponse}<span style="font-size:16px;font-weight:500;color:var(--text-muted)"> min</span>`;
  if (tableCount) tableCount.textContent = `${total} records`;
}

function applyFilters() {
  const dateFrom = document.getElementById('dateFrom').value;
  const dateTo = document.getElementById('dateTo').value;
  const area = document.querySelectorAll('.filter-select')[0].value;
  const camera = document.querySelectorAll('.filter-select')[1].value;

  let filtered = [...tableData];

  if (dateFrom) {
    const fromTime = new Date(dateFrom + 'T00:00:00').getTime();
    filtered = filtered.filter(i => new Date(i.detectedAt).getTime() >= fromTime);
  }
  if (dateTo) {
    const toTime = new Date(dateTo + 'T23:59:59.999').getTime();
    filtered = filtered.filter(i => new Date(i.detectedAt).getTime() <= toTime);
  }
  if (area !== 'All Areas') {
    filtered = filtered.filter(i => i.locationName === area);
  }
  if (camera !== 'All Cameras') {
    filtered = filtered.filter(i => i.camera === camera);
  }

  renderTable(filtered);
}

function renderTable(data) {
  const tbody = document.getElementById('incidentTable');

  tbody.innerHTML = data.map((row, index) => {
    const sevBadge = `<span class="badge badge-${row.severity}">
      <span class="severity-dot ${row.severity}"></span>
      ${row.severity.charAt(0).toUpperCase() + row.severity.slice(1)}
    </span>`;

    let statusTag;
    if (row.status === 'emergency') {
      statusTag = '<span class="status-tag emergency">Emergency</span>';
    } else if (row.status === 'false-alert') {
      statusTag = '<span class="status-tag false-alert">False Alert</span>';
    } else {
      statusTag = '<span class="status-tag pending">Pending</span>';
    }

    const responseClass = !row.responseTimeMins ? '' :
      (row.responseTimeMins <= 3 ? 'fast' :
      row.responseTimeMins <= 5 ? 'normal' : 'slow');

    const dateStr = new Date(row.detectedAt).toLocaleDateString();
    const timeStr = new Date(row.detectedAt).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'});

    return `
      <tr class="clickable-row" onclick="showIncident(${index})">
        <td>${dateStr}</td>
        <td>${timeStr}</td>
        <td>${row.locationName}</td>
        <td>${row.camera}</td>
        <td>${row.type}</td>
        <td>${sevBadge}</td>
        <td>${statusTag}</td>
        <td class="response-time ${responseClass}">
          ${!row.responseTimeMins ? '—' : row.responseTimeMins + ' min'}
        </td>
      </tr>
    `;
  }).join('');
}
function showIncident(index) {
  const i = tableData[index];

  const modal = document.getElementById("incidentModal");
  const content = document.getElementById("modalContent");

  const dateStr = i.detectedAt
    ? new Date(i.detectedAt).toLocaleDateString()
    : '2026-03-10';

  const timeStr = i.detectedAt
    ? new Date(i.detectedAt).toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'})
    : '12:52';

  const videoUrl = i.videoUrl || i.videoURL || i.video || '';
  const mediaHtml = videoUrl
    ? `<video class="incident-video" src="${videoUrl}" muted autoplay loop controls playsinline onerror="this.outerHTML='<div class=\'camera-feed-placeholder\'><i class=\'fa-solid fa-video-slash\' style=\'font-size:32px;opacity:0.3\'></i><span style=\'font-size:13px;opacity:0.6;font-weight:600;\'>Camera Recording Unavailable</span></div>'"></video>`
    : `<div class="camera-feed-placeholder"><i class="fa-solid fa-video-slash" style="font-size:32px;opacity:0.3"></i><span style="font-size:13px;opacity:0.6;font-weight:600;">Camera Recording Unavailable</span></div>`;

  content.innerHTML = `
    <div class="incident-header">
      <h2>${i.type ?? 'Accident'}</h2>
      <button class="close-btn" onclick="closeModal()">✕</button>
    </div>

    <div class="incident-media">
      <div class="incident-media-title">Camera Recording</div>
      ${mediaHtml}
    </div>

    <div class="incident-body">

      <p class="incident-desc">
        ${i.description ?? 'Collision due to wet road.'}
      </p>

      <div class="row"><span>📍 Area</span><strong>${i.locationName ?? 'Stanley Bridge'}</strong></div>
      <div class="row"><span>📅 Date</span><strong>${dateStr}</strong></div>

      <div class="row"><span>⏰ Time</span><strong>${timeStr}</strong></div>
      <div class="row"><span>📷 Camera</span><strong>${i.camera ?? 'CAM_22'}</strong></div>

      <div class="row"><span>🚨 Type</span><strong>${i.type ?? 'Accident'}</strong></div>
      <div class="row"><span>⚠️ Severity</span><strong>${i.severity ?? 'high'}</strong></div>

      <div class="row"><span>📊 Status</span><strong>${i.status ?? 'emergency'}</strong></div>
      <div class="row"><span>🚑 Response</span><strong>${i.responseTimeMins ?? '1.8'} min</strong></div>

      <div class="row"><span>🚗 Vehicles</span><strong>${i.vehicles ?? '3'}</strong></div>
      <div class="row"><span>⚠️ Cause</span><strong>${i.cause ?? 'Rain & speed'}</strong></div>

      <div class="row full">
        <span>📍 Location</span>
        <strong>${i.coordinates ?? '31.2156,29.9553'}</strong>
      </div>
      <div id="incidentMap"></div>
      <button class="map-btn" data-location="${i.coordinates ?? '31.2156,29.9553'}">
  📍 View on Map
</button>

    </div>
  `;

  modal.classList.remove("hidden");

  /* Map Button */
  const btn = content.querySelector('.map-btn');
  btn.addEventListener('click', () => {
    const location = btn.dataset.location;
    if (!location) return;
  
    const [lat, lng] = location.split(',');
  
    window.open(`map.html?lat=${lat}&lng=${lng}`, '_blank');
  });}

/* Close */
function closeModal() {
  document.getElementById("incidentModal").classList.add("hidden");
}

/* Click outside */
window.onclick = function(e) {
  const modal = document.getElementById("incidentModal");
  if (e.target === modal) {
    modal.classList.add("hidden");
  }
};

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
        alert('User created successfully.\nCredentials have been emailed to: ' + email);
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

// ===================== CHARTS =====================
// function initCharts() {
//   Chart.defaults.font.family = "'Inter', sans-serif";
//   Chart.defaults.font.size = 12;
//   Chart.defaults.color = '#374151';
  
//   // Line Chart (Static mock for demonstration)
//   const lineCtx = document.getElementById('lineChart').getContext('2d');
//   new Chart(lineCtx, {
//     type: 'bar',
//     data: {
//       labels: ['Mar 4', 'Mar 5', 'Mar 6', 'Mar 7', 'Mar 8', 'Mar 9', 'Mar 10'],
//       datasets: [
//         { label: 'High', data: [8, 5, 10, 7, 9, 6, 12], backgroundColor: '#E53935', borderRadius: 4, barPercentage: 0.7, categoryPercentage: 0.75 },
//         { label: 'Medium', data: [12, 15, 9, 14, 11, 13, 16], backgroundColor: '#FFB300', borderRadius: 4, barPercentage: 0.7, categoryPercentage: 0.75 },
//         { label: 'Low', data: [6, 4, 8, 5, 7, 9, 10], backgroundColor: '#16C79A', borderRadius: 4, barPercentage: 0.7, categoryPercentage: 0.75 },
//       ],
//     },
//     options: {
//       responsive: true,
//       maintainAspectRatio: false,
//       plugins: {
//         legend: { position: 'top', align: 'end', labels: { boxWidth: 8, boxHeight: 8, borderRadius: 2, useBorderRadius: true, padding: 16, font: { size: 11, weight: '500' } } },
//         tooltip: { backgroundColor: '#1F2933', titleFont: { size: 12, weight: '600' }, bodyFont: { size: 12 }, cornerRadius: 6, padding: 10 },
//       },
//       scales: {
//         x: { grid: { display: false }, ticks: { font: { size: 11 } } },
//         y: { beginAtZero: true, grid: { color: '#E8ECF1', drawBorder: false }, ticks: { font: { size: 11 }, stepSize: 5 } },
//       },
//     },
//   });

//   // Calculate severity counts dynamically
//   let high = 0, medium = 0, low = 0;
//   tableData.forEach(inc => {
//     if (inc.severity === 'high') high++;
//     else if (inc.severity === 'medium') medium++;
//     else low++;
//   });

//   // Doughnut Chart
//   const doughnutCtx = document.getElementById('doughnutChart').getContext('2d');
//   new Chart(doughnutCtx, {
//     type: 'doughnut',
//     data: {
//       labels: ['High', 'Medium', 'Low'],
//       datasets: [{
//         data: [high, medium, low],
//         backgroundColor: ['#E53935', '#FFB300', '#16C79A'],
//         borderWidth: 0,
//         spacing: 3,
//         borderRadius: 4,
//       }],
//     },
//     options: {
//       responsive: true,
//       maintainAspectRatio: false,
//       cutout: '65%',
//       plugins: {
//         legend: { position: 'bottom', labels: { boxWidth: 10, boxHeight: 10, borderRadius: 3, useBorderRadius: true, padding: 16, font: { size: 12, weight: '500' }, color: '#52606D' } },
//         tooltip: {
//           backgroundColor: '#1F2933', titleFont: { size: 12, weight: '600' }, bodyFont: { size: 12 }, cornerRadius: 6, padding: 10,
//           callbacks: {
//             label: function(context) {
//               const total = context.dataset.data.reduce((a, b) => a + b, 0);
//               const pct = total ? Math.round(context.raw / total * 100) : 0;
//               return ` ${context.label}: ${context.raw} (${pct}%)`;
//             }
//           }
//         },
//       },
//     },
//   });
// }

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
