// ── Theme ─────────────────────────────────────
function toggleTheme() {
  var dark = document.body.classList.toggle("dark");
  localStorage.setItem("theme", dark ? "dark" : "light");
  var icon  = document.getElementById("theme-icon");
  var label = document.getElementById("theme-label");
  if (icon)  icon.className    = dark ? "ti ti-sun" : "ti ti-moon";
  if (label) label.textContent = dark ? "Light mode" : "Dark mode";
}
(function() {
  if (localStorage.getItem("theme") === "dark") {
    document.body.classList.add("dark");
    var icon  = document.getElementById("theme-icon");
    var label = document.getElementById("theme-label");
    if (icon)  icon.className    = "ti ti-sun";
    if (label) label.textContent = "Light mode";
  }
})();

// ── File upload ───────────────────────────────
function handleFile(input) {
  var file = input.files[0];
  if (!file) return;
  var chosen = document.getElementById("file-chosen");
  var btn    = document.getElementById("submit-btn");
  var title  = document.getElementById("drop-title");
  var sub    = document.getElementById("drop-sub");
  var kb     = (file.size / 1024).toFixed(1);
  if (chosen) {
    chosen.style.display = "flex";
    chosen.innerHTML =
      '<i class="ti ti-file-spreadsheet"></i> ' +
      file.name + ' (' + kb + ' KB)';
  }
  if (btn)   btn.style.display   = "inline-flex";
  if (title) title.textContent   = "File ready!";
  if (sub)   sub.textContent     =
    "Click Analyse to start processing";
  showToast("File selected: " + file.name);
}

// ── Drag and drop ─────────────────────────────
var dz = document.getElementById("drop-zone");
if (dz) {
  ["dragenter","dragover"].forEach(function(e) {
    dz.addEventListener(e, function(ev) {
      ev.preventDefault();
      dz.classList.add("drag-over");
    });
  });
  ["dragleave","drop"].forEach(function(e) {
    dz.addEventListener(e, function() {
      dz.classList.remove("drag-over");
    });
  });
  dz.addEventListener("drop", function(ev) {
    ev.preventDefault();
    var file = ev.dataTransfer.files[0];
    if (file && file.name.endsWith(".csv")) {
      var inp = document.getElementById("file-input");
      var dt  = new DataTransfer();
      dt.items.add(file);
      inp.files = dt.files;
      handleFile(inp);
    }
  });
}

// ── Tab switcher ──────────────────────────────
function switchTab(name) {
  document.querySelectorAll(".rtab").forEach(function(t) {
    t.classList.remove("active");
  });
  document.querySelectorAll(".tab-panel").forEach(function(p) {
    p.classList.remove("active");
  });
  var tab   = document.getElementById("tab-"   + name);
  var panel = document.getElementById("panel-" + name);
  if (tab)   tab.classList.add("active");
  if (panel) panel.classList.add("active");
}

// ── Toast ─────────────────────────────────────
function showToast(msg) {
  var t = document.getElementById("toast");
  if (!t) return;
  t.textContent    = msg;
  t.style.display  = "block";
  setTimeout(function() { t.style.display = "none"; }, 3000);
}

// ── Loading animations ────────────────────────
var ANIMS = [
  '<div class="anim1"><div class="load">' +
    '<hr/><hr/><hr/><hr/></div></div>',
  '<div class="anim2"><div class="load">' +
    '<span></span><span></span>' +
    '<span></span><span></span></div></div>',
  '<div class="anim3"><div class="load">' +
    '<span></span><span></span>' +
    '<span></span><span></span></div></div>',
];
var TITLES = [
  "Analysing your data...",
  "Running AI models...",
  "Building your report...",
];
var currentAnim = Math.floor(Math.random() * 3);

function showAnim(idx) {
  currentAnim = idx;
  var c = document.getElementById("anim-container");
  var t = document.getElementById("loading-title");
  if (c) c.innerHTML    = ANIMS[idx];
  if (t) t.textContent  = TITLES[idx];
  for (var i = 0; i < 3; i++) {
    var dot = document.getElementById("dot" + i);
    if (dot) {
      if (i === idx) dot.classList.add("active");
      else           dot.classList.remove("active");
    }
  }
}

function initLoading() {
  showAnim(currentAnim);
}