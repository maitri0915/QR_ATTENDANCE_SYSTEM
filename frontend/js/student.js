Auth.guard("student");
document.getElementById("whoName").textContent = Auth.fullName() || "Student";

let scanStream = null;
let scanRafHandle = null;
let scanLocked = false; // prevents duplicate submissions while a scan is being processed

// ---------------- Navigation ----------------
document.querySelectorAll("#sideNav a").forEach((link) => {
  link.addEventListener("click", (e) => {
    e.preventDefault();
    document.querySelectorAll("#sideNav a").forEach((a) => a.classList.remove("active"));
    link.classList.add("active");
    document.querySelectorAll(".main > section").forEach((s) => (s.style.display = "none"));
    document.getElementById(`sec-${link.dataset.section}`).style.display = "block";

    if (link.dataset.section !== "scan") stopScan();
    if (link.dataset.section === "attendance") loadAttendance();
    if (link.dataset.section === "leave") loadLeave();
    if (link.dataset.section === "profile") loadProfile();
  });
});

// ---------------- QR Scanning ----------------
async function startScan() {
  const video = document.getElementById("video");
  const errEl = document.getElementById("scanErr");
  try {
    scanStream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" } });
    video.srcObject = scanStream;
    await video.play();
    document.getElementById("startScanBtn").style.display = "none";
    document.getElementById("stopScanBtn").style.display = "inline-block";
    scanLocked = false;
    tickScan();
  } catch (err) {
    showError(errEl, new Error("Could not access the camera. Check your browser's camera permission."));
  }
}

function stopScan() {
  if (scanRafHandle) cancelAnimationFrame(scanRafHandle);
  if (scanStream) {
    scanStream.getTracks().forEach((t) => t.stop());
    scanStream = null;
  }
  document.getElementById("startScanBtn").style.display = "inline-block";
  document.getElementById("stopScanBtn").style.display = "none";
}

function tickScan() {
  const video = document.getElementById("video");
  const canvas = document.getElementById("canvas");
  const ctx = canvas.getContext("2d");

  if (video.readyState === video.HAVE_ENOUGH_DATA && !scanLocked) {
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
    const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
    const code = jsQR(imageData.data, imageData.width, imageData.height);
    if (code && code.data) {
      handleScannedPayload(code.data);
    }
  }
  if (scanStream) scanRafHandle = requestAnimationFrame(tickScan);
}

/** Resolves to {latitude, longitude} or null if unavailable/denied — never rejects. */
function getCurrentLocation() {
  return new Promise((resolve) => {
    if (!navigator.geolocation) return resolve(null);
    navigator.geolocation.getCurrentPosition(
      (pos) => resolve({ latitude: pos.coords.latitude, longitude: pos.coords.longitude }),
      () => resolve(null),
      { enableHighAccuracy: true, timeout: 8000 }
    );
  });
}

async function handleScannedPayload(payload) {
  // QR encodes "qr_id|token"
  const parts = payload.split("|");
  if (parts.length !== 2) return;
  const [qrId, token] = parts;

  scanLocked = true;
  try {
    const loc = await getCurrentLocation();
    await Api.post("/api/student/attendance/scan", {
      qr_id: qrId,
      token,
      student_latitude: loc ? loc.latitude : null,
      student_longitude: loc ? loc.longitude : null,
    });
    showSuccess(document.getElementById("scanOk"), "Attendance marked — you're checked in!");
    stopScan();
  } catch (err) {
    showError(document.getElementById("scanErr"), err);
    setTimeout(() => { scanLocked = false; }, 2000); // allow retry on the next distinct frame
  }
}

// ---------------- Attendance History / Analytics ----------------
async function loadAttendance() {
  const [history, analytics] = await Promise.all([
    Api.get("/api/student/attendance/history"),
    Api.get("/api/student/attendance/analytics"),
  ]);

  document.getElementById("analyticsRow").innerHTML = analytics.length
    ? analytics.map((a) => `
        <div class="stat-block ${a.is_defaulter ? "warn" : "good"}">
          <div class="num">${a.attendance_percentage}%</div>
          <div class="label">Subject #${a.subject_id} ${a.is_defaulter ? "· Below 75%" : ""}</div>
        </div>`).join("")
    : `<div class="empty-state">No attendance recorded yet — scan a QR to get started.</div>`;

  const tbody = document.querySelector("#historyTable tbody");
  tbody.innerHTML = history.length
    ? history.map((r) => `<tr><td class="num">#${r.session_id}</td><td>${statusPill(r.status)}</td><td>${r.marking_method}</td><td class="mono" style="font-size:12px;">${fmtDateTime(r.check_in_timestamp)}</td></tr>`).join("")
    : `<tr><td colspan="4" class="empty-state">No sessions attended yet.</td></tr>`;
}

// ---------------- Leave ----------------
document.getElementById("leaveForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    await Api.post("/api/student/leave-requests", {
      start_date: document.getElementById("leaveStart").value,
      end_date: document.getElementById("leaveEnd").value,
      reason: document.getElementById("leaveReason").value.trim(),
    });
    document.getElementById("leaveForm").reset();
    showSuccess(document.getElementById("leaveOk"), "Leave request submitted.");
    loadLeave();
  } catch (err) { showError(document.getElementById("leaveErr"), err); }
});

async function loadLeave() {
  const leaves = await Api.get("/api/student/leave-requests/mine");
  const tbody = document.querySelector("#leaveTable tbody");
  tbody.innerHTML = leaves.length
    ? leaves.map((l) => `<tr><td class="num">${l.start_date} → ${l.end_date}</td><td>${l.reason}</td><td>${statusPill(l.status)}</td></tr>`).join("")
    : `<tr><td colspan="3" class="empty-state">You haven't submitted any leave requests.</td></tr>`;
}

// ---------------- Profile ----------------
async function loadProfile() {
  const p = await Api.get("/api/auth/me");
  document.getElementById("profileView").innerHTML = `
    <table class="ledger">
      <tbody>
        <tr><td>Name</td><td>${p.full_name}</td></tr>
        <tr><td>Email</td><td class="mono">${p.email}</td></tr>
        <tr><td>Roll number</td><td class="mono">${p.internal_id || "—"}</td></tr>
        <tr><td>Semester</td><td>${p.current_semester || "—"}</td></tr>
      </tbody>
    </table>`;
  document.getElementById("pPhone").value = p.phone || "";
  document.getElementById("pDivision").value = p.division_section || "";
}

document.getElementById("profileForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  await Api.put("/api/student/profile", {
    phone: document.getElementById("pPhone").value.trim() || null,
    division_section: document.getElementById("pDivision").value.trim() || null,
  });
  showSuccess(document.getElementById("profileOk"), "Profile updated.");
});

// ---------------- Init ----------------
// Scan tab is the default view; nothing to preload.
