Auth.guard("faculty");
document.getElementById("whoName").textContent = Auth.fullName() || "Faculty";

let allocationsCache = [];
let currentSessionId = null;
let qrTimerHandle = null;
let liveTimerHandle = null;
const QR_VALIDITY_SECONDS = 30;

let classroomLat = null;
let classroomLng = null;

/** Captures the faculty device's current location to use as the "classroom" reference point. */
function captureClassroomLocation() {
  const statusEl = document.getElementById("locStatus");
  if (!navigator.geolocation) {
    if (statusEl) statusEl.textContent = "Location: not supported on this device (proximity check will be skipped)";
    return;
  }
  navigator.geolocation.getCurrentPosition(
    (pos) => {
      classroomLat = pos.coords.latitude;
      classroomLng = pos.coords.longitude;
      if (statusEl) statusEl.textContent = `Location: captured (±${Math.round(pos.coords.accuracy)}m accuracy)`;
    },
    () => {
      if (statusEl) statusEl.textContent = "Location: permission denied (proximity check will be skipped for this session)";
    },
    { enableHighAccuracy: true, timeout: 8000 }
  );
}

// ---------------- Navigation ----------------
document.querySelectorAll("#sideNav a").forEach((link) => {
  link.addEventListener("click", (e) => {
    e.preventDefault();
    document.querySelectorAll("#sideNav a").forEach((a) => a.classList.remove("active"));
    link.classList.add("active");
    document.querySelectorAll(".main > section").forEach((s) => (s.style.display = "none"));
    document.getElementById(`sec-${link.dataset.section}`).style.display = "block";
    if (link.dataset.section === "classes") loadClasses();
    if (link.dataset.section === "leave") loadLeaveRequests();
    if (link.dataset.section === "session" && !currentSessionId) { loadAllocOptions(); captureClassroomLocation(); }
  });
});

// ---------------- My Classes ----------------
async function loadClasses() {
  allocationsCache = await Api.get("/api/faculty/my-allocations");
  const tbody = document.querySelector("#classTable tbody");
  tbody.innerHTML = allocationsCache.length
    ? allocationsCache.map((a) => `<tr><td>Subject #${a.subject_id}</td><td class="num">${a.assigned_semester}</td><td class="num">${a.assigned_division}</td><td><button class="btn-sm" onclick="goStartSession(${a.allocation_id})">Start session</button></td></tr>`).join("")
    : `<tr><td colspan="4" class="empty-state">No classes assigned to you yet — ask your administrator to allocate one.</td></tr>`;
}

function goStartSession(allocationId) {
  document.querySelector('[data-section="session"]').click();
  setTimeout(() => { document.getElementById("sessionAlloc").value = allocationId; }, 50);
}

async function loadAllocOptions() {
  if (!allocationsCache.length) allocationsCache = await Api.get("/api/faculty/my-allocations");
  document.getElementById("sessionAlloc").innerHTML = allocationsCache.length
    ? allocationsCache.map((a) => `<option value="${a.allocation_id}">Subject #${a.subject_id} · Sem ${a.assigned_semester} · Div ${a.assigned_division}</option>`).join("")
    : `<option value="">No classes assigned</option>`;
}

// ---------------- Session + QR ----------------
async function startSession() {
  try {
    const allocationId = parseInt(document.getElementById("sessionAlloc").value, 10);
    if (!allocationId) throw new Error("You have no assigned classes yet.");

    const now = new Date();
    const end = new Date(now.getTime() + 60 * 60 * 1000);

    const session = await Api.post("/api/faculty/sessions", {
      allocation_id: allocationId,
      session_type: document.getElementById("sessionType").value,
      scheduled_date: now.toISOString().slice(0, 10),
      start_time: now.toISOString(),
      scheduled_end_time: end.toISOString(),
      classroom_latitude: classroomLat,
      classroom_longitude: classroomLng,
    });

    currentSessionId = session.session_id;
    document.getElementById("sessionSetupPanel").style.display = "none";
    document.getElementById("liveSessionPanel").style.display = "block";

    refreshQr();
    qrTimerHandle = setInterval(refreshQr, QR_VALIDITY_SECONDS * 1000);
    liveTimerHandle = setInterval(refreshLive, 4000);
    refreshLive();
    loadRoster();
  } catch (err) {
    showError(document.getElementById("sessionErr"), err);
  }
}

let countdownInterval = null;
async function refreshQr() {
  const qr = await Api.post(`/api/faculty/sessions/${currentSessionId}/qr/generate`, {});
  document.getElementById("qrImage").src = `data:image/png;base64,${qr.qr_image_base64}`;

  let secondsLeft = QR_VALIDITY_SECONDS;
  document.getElementById("countdown").textContent = secondsLeft;
  clearInterval(countdownInterval);
  countdownInterval = setInterval(() => {
    secondsLeft -= 1;
    document.getElementById("countdown").textContent = Math.max(secondsLeft, 0);
    if (secondsLeft <= 0) clearInterval(countdownInterval);
  }, 1000);
}

async function refreshLive() {
  if (!currentSessionId) return;
  const roster = await Api.get(`/api/faculty/sessions/${currentSessionId}/live`);
  const presentCount = roster.filter((r) => r.status === "present").length;
  document.getElementById("presentCount").textContent = presentCount;

  const tbody = document.querySelector("#liveTable tbody");
  tbody.innerHTML = roster.length
    ? roster.map((r) => `
        <tr>
          <td>${r.full_name}</td>
          <td class="num">${r.internal_id || "—"}</td>
          <td>${statusPill(r.status)}</td>
          <td class="mono" style="font-size:13px;">${r.check_in_timestamp ? fmtDateTime(r.check_in_timestamp) : "—"}</td>
        </tr>`).join("")
    : `<tr><td colspan="4" class="empty-state">No students found for this class's semester/division.</td></tr>`;
}

async function loadRoster() {
  const select = document.getElementById("manualProfileId");
  try {
    const roster = await Api.get(`/api/faculty/sessions/${currentSessionId}/roster`);
    select.innerHTML = roster.length
      ? roster.map((s) => `<option value="${s.profile_id}">${s.full_name} (${s.internal_id || "#" + s.profile_id})</option>`).join("")
      : `<option value="">No students found for this semester/division</option>`;
  } catch (err) {
    select.innerHTML = `<option value="">Could not load roster</option>`;
  }
}

async function manualMark() {
  const profileId = parseInt(document.getElementById("manualProfileId").value, 10);
  const status = document.getElementById("manualStatus").value;
  const errEl = document.getElementById("manualErr");
  if (!profileId) return;
  try {
    await Api.post(`/api/faculty/sessions/${currentSessionId}/attendance/manual`, { student_profile_id: profileId, status });
    refreshLive();
  } catch (err) {
    showError(errEl, err);
  }
}

async function closeSession() {
  if (!confirm("Close this session? Students will no longer be able to mark attendance.")) return;
  await Api.post(`/api/faculty/sessions/${currentSessionId}/close`, {});
  clearInterval(qrTimerHandle);
  clearInterval(liveTimerHandle);
  clearInterval(countdownInterval);
  currentSessionId = null;
  document.getElementById("liveSessionPanel").style.display = "none";
  document.getElementById("sessionSetupPanel").style.display = "block";
}

// ---------------- Leave Requests ----------------
async function loadLeaveRequests() {
  const leaves = await Api.get("/api/faculty/leave-requests/pending");
  const tbody = document.querySelector("#leaveTable tbody");
  tbody.innerHTML = leaves.length
    ? leaves.map((l) => `
        <tr>
          <td class="num">#${l.student_profile_id}</td>
          <td class="num">${l.start_date} → ${l.end_date}</td>
          <td>${l.reason}</td>
          <td class="mono" style="font-size:12px;">${fmtDateTime(l.submitted_at)}</td>
          <td style="white-space:nowrap;">
            <button class="btn-sm" onclick="decideLeave(${l.leave_id}, 'approved')">Approve</button>
            <button class="btn-sm btn-danger" onclick="decideLeave(${l.leave_id}, 'rejected')">Reject</button>
          </td>
        </tr>`).join("")
    : `<tr><td colspan="5" class="empty-state">No pending leave requests.</td></tr>`;
}

async function decideLeave(leaveId, status) {
  await Api.post(`/api/faculty/leave-requests/${leaveId}/decision`, { status });
  loadLeaveRequests();
}

// ---------------- Init ----------------
loadClasses();
