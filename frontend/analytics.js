// Authentication check
const token = localStorage.getItem('token');
const user = JSON.parse(localStorage.getItem('user'));
if (!token) {
  window.location.href = 'index.html';
}

let tableData = [];

// ===================== MULTI-SELECT DROPDOWN =====================
function toggleMultiselect(wrapId) {
    var wrap = document.getElementById(wrapId);
    var trigger = wrap.querySelector('.multiselect-trigger');
    var dropdown = wrap.querySelector('.multiselect-dropdown');
    var isOpen = dropdown.classList.contains('visible');
  
    // Close all other open dropdowns first
    document.querySelectorAll('.multiselect-dropdown.visible').forEach(function(dd) {
      dd.classList.remove('visible');
      dd.closest('.multiselect-wrap').querySelector('.multiselect-trigger').classList.remove('open');
    });
  
    if (!isOpen) {
      dropdown.classList.add('visible');
      trigger.classList.add('open');
    }
}
  
function handleSelectAll(checkbox) {
    var allChecked = checkbox.checked;
    var areaCbs = document.querySelectorAll('.area-cb');
    areaCbs.forEach(function(cb) {
      cb.checked = allChecked;
    });
    updateAreaLabel();
}
  
function updateAreaLabel() {
    var areaCbs = document.querySelectorAll('.area-cb');
    var checked = document.querySelectorAll('.area-cb:checked');
    var allBox = document.getElementById('area-all');
    var label = document.querySelector('#areaMultiselect .ms-label');
  
    // Sync "All Areas" checkbox
    if (checked.length === areaCbs.length) {
      allBox.checked = true;
      label.textContent = 'All Areas';
    } else if (checked.length === 0) {
      allBox.checked = false;
      label.textContent = 'No Areas Selected';
    } else {
      allBox.checked = false;
      if (checked.length === 1) {
        label.textContent = checked[0].nextElementSibling.textContent;
      } else {
        label.textContent = checked.length + ' areas selected';
      }
    }
}

function populateAreaFilter(data) {
  const areas = [...new Set(data.map(i => i.locationName))].sort();
  const dropdown = document.querySelector('#areaMultiselect .multiselect-dropdown');
  
  // Keep "All Areas"
  const allAreasHtml = `
    <label class="ms-option">
      <input type="checkbox" id="area-all" checked onchange="handleSelectAll(this)">
      <span>All Areas</span>
    </label>
  `;
  
  const optionsHtml = areas.map(a => `
    <label class="ms-option">
      <input type="checkbox" class="area-cb" checked onchange="updateAreaLabel()">
      <span>${a}</span>
    </label>
  `).join('');
  
  dropdown.innerHTML = allAreasHtml + optionsHtml;
}
  
function applyFilters() {
    const dateFrom = document.getElementById('dateFrom').value;
    const dateTo = document.getElementById('dateTo').value;
    
    // Get checked areas
    const checkedAreas = Array.from(document.querySelectorAll('.area-cb:checked')).map(cb => cb.nextElementSibling.textContent);
    const allAreasChecked = document.getElementById('area-all').checked;

    let filtered = [...tableData];

    if (dateFrom) {
      const fromTime = new Date(dateFrom + 'T00:00:00').getTime();
      filtered = filtered.filter(i => new Date(i.detectedAt).getTime() >= fromTime);
    }
    if (dateTo) {
      const toTime = new Date(dateTo + 'T23:59:59.999').getTime();
      filtered = filtered.filter(i => new Date(i.detectedAt).getTime() <= toTime);
    }
    if (!allAreasChecked) {
      filtered = filtered.filter(i => checkedAreas.includes(i.locationName));
    }

    updateDashboard(filtered);

    // Close dropdown
    document.querySelectorAll('.multiselect-dropdown.visible').forEach(function(dd) {
      dd.classList.remove('visible');
      dd.closest('.multiselect-wrap').querySelector('.multiselect-trigger').classList.remove('open');
    });
}
  
// Close dropdown when clicking outside
document.addEventListener('click', function(e) {
    if (!e.target.closest('.multiselect-wrap')) {
      document.querySelectorAll('.multiselect-dropdown.visible').forEach(function(dd) {
        dd.classList.remove('visible');
        dd.closest('.multiselect-wrap').querySelector('.multiselect-trigger').classList.remove('open');
      });
    }
});

// ===================== CHARTS =====================
let charts = {};

function initCharts(data) {
    Chart.defaults.font.family = "'Inter', sans-serif";
    Chart.defaults.font.size = 12;
    Chart.defaults.color = '#374151';

    // 1. Severity Chart
    const sevCounts = { high: 0, medium: 0, low: 0 };
    data.forEach(i => sevCounts[i.severity]++);

    const severityCtx = document.getElementById('severityChart').getContext('2d');
    charts.severity = new Chart(severityCtx, {
      type: 'pie',
      data: {
        labels: ['High', 'Medium', 'Low'],
        datasets: [{
          data: [sevCounts.high, sevCounts.medium, sevCounts.low],
          backgroundColor: ['#E53935', '#FFB300', '#16C79A'],
          borderWidth: 0,
          spacing: 2,
          borderRadius: 3,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { position: 'right' }
        }
      }
    });

    // 2. Over Time Chart (Last 7 Days)
    const days = [];
    const highData = [], medData = [], lowData = [];
    for(let i=6; i>=0; i--) {
      const d = new Date();
      d.setDate(d.getDate() - i);
      const dateStr = d.toLocaleDateString([], {month:'short', day:'numeric'});
      days.push(dateStr);
      
      const dayIncidents = data.filter(inc => new Date(inc.detectedAt).toDateString() === d.toDateString());
      highData.push(dayIncidents.filter(inc => inc.severity === 'high').length);
      medData.push(dayIncidents.filter(inc => inc.severity === 'medium').length);
      lowData.push(dayIncidents.filter(inc => inc.severity === 'low').length);
    }

    const lineCtx = document.getElementById('lineChart').getContext('2d');
    charts.line = new Chart(lineCtx, {
      type: 'bar',
      data: {
        labels: days,
        datasets: [
          { label: 'High', data: highData, backgroundColor: '#E53935', borderRadius: 4 },
          { label: 'Medium', data: medData, backgroundColor: '#FFB300', borderRadius: 4 },
          { label: 'Low', data: lowData, backgroundColor: '#16C79A', borderRadius: 4 },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: { y: { beginAtZero: true, ticks: { stepSize: 1 } } }
      }
    });

    // 3. Sector Chart
    const sectors = {};
    data.forEach(i => {
      sectors[i.locationName] = (sectors[i.locationName] || 0) + 1;
    });
    const sectorLabels = Object.keys(sectors);
    const sectorValues = Object.values(sectors);

    const sectorCtx = document.getElementById('sectorChart').getContext('2d');
    charts.sector = new Chart(sectorCtx, {
      type: 'bar',
      data: {
        labels: sectorLabels,
        datasets: [{
          label: 'Incidents',
          data: sectorValues,
          backgroundColor: '#3d5afe',
          borderRadius: 4,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        indexAxis: 'y',
      }
    });

    // 4. Day of Month Chart
    const monthDays = Array.from({length: 31}, (_, i) => i + 1);
    const monthData = monthDays.map(day => {
      return data.filter(i => new Date(i.detectedAt).getDate() === day).length;
    });

    const dayCtx = document.getElementById('dayChart').getContext('2d');
    charts.day = new Chart(dayCtx, {
      type: 'line',
      data: {
        labels: monthDays,
        datasets: [{
          label: 'Incidents',
          data: monthData,
          borderColor: '#E53935',
          fill: true,
          backgroundColor: 'rgba(229, 57, 53, 0.1)',
          tension: 0.3
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
      }
    });
}

function updateDashboard(data) {
  // Update KPIs
  document.querySelectorAll('.av2-kpi-value')[0].textContent = data.length;
  const avg = data.length / 30; // rough average per day for the month
  document.querySelectorAll('.av2-kpi-value')[1].textContent = avg.toFixed(1);

  // Update Charts
  if (charts.severity) {
    const sevCounts = { high: 0, medium: 0, low: 0 };
    data.forEach(i => sevCounts[i.severity]++);
    charts.severity.data.datasets[0].data = [sevCounts.high, sevCounts.medium, sevCounts.low];
    charts.severity.update();
  }
  
  if (charts.line) {
    const highData = [], medData = [], lowData = [];
    for(let i=6; i>=0; i--) {
      const d = new Date();
      d.setDate(d.getDate() - i);
      const dayIncidents = data.filter(inc => new Date(inc.detectedAt).toDateString() === d.toDateString());
      highData.push(dayIncidents.filter(inc => inc.severity === 'high').length);
      medData.push(dayIncidents.filter(inc => inc.severity === 'medium').length);
      lowData.push(dayIncidents.filter(inc => inc.severity === 'low').length);
    }
    charts.line.data.datasets[0].data = highData;
    charts.line.data.datasets[1].data = medData;
    charts.line.data.datasets[2].data = lowData;
    charts.line.update();
  }

  if (charts.sector) {
    const sectors = {};
    data.forEach(i => {
      sectors[i.locationName] = (sectors[i.locationName] || 0) + 1;
    });
    charts.sector.data.labels = Object.keys(sectors);
    charts.sector.data.datasets[0].data = Object.values(sectors);
    charts.sector.update();
  }

  if (charts.day) {
    const monthDays = Array.from({length: 31}, (_, i) => i + 1);
    charts.day.data.datasets[0].data = monthDays.map(day => {
      return data.filter(i => new Date(i.detectedAt).getDate() === day).length;
    });
    charts.day.update();
  }
}

async function fetchAnalytics() {
  try {
    const res = await fetch('/api/incidents', {
      headers: { 'Authorization': `Bearer ${token}` }
    });
    if (res.ok) {
      const data = await res.json();
      tableData = data.incidents || [];
      populateAreaFilter(tableData);
      initCharts(tableData);
      updateDashboard(tableData);
    }
  } catch (error) {
    console.error('Failed to fetch analytics', error);
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

// ===================== INIT =====================
document.addEventListener('DOMContentLoaded', function() {
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
});

// Admin Modal (copy from dashboard.js)
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
