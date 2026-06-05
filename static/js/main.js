// ── Performance utilities ──────────────────────
var debounce = function(func, wait) {
  var timeout;
  return function() {
    var context = this, args = arguments;
    clearTimeout(timeout);
    timeout = setTimeout(function() {
      func.apply(context, args);
    }, wait);
  };
};

var throttle = function(func, limit) {
  var inThrottle;
  return function() {
    var args = arguments, context = this;
    if (!inThrottle) {
      func.apply(context, args);
      inThrottle = true;
      setTimeout(function() { inThrottle = false; }, limit);
    }
  };
};

// ── Toast Notifications (Enhanced) ──────────
function showToast(msg, type) {
  type = type || 'info';
  var container = document.getElementById("toast-container");
  
  if (!container) {
    container = document.createElement("div");
    container.id = "toast-container";
    container.className = "toast-container";
    document.body.appendChild(container);
  }
  
  var toast = document.createElement("div");
  toast.className = "toast " + type;
  
  var iconMap = {
    'success': 'ti-check',
    'error': 'ti-alert-circle',
    'warning': 'ti-alert-triangle',
    'info': 'ti-info-circle'
  };
  
  var icon = iconMap[type] || 'ti-info-circle';
  
  toast.innerHTML = 
    '<div class="toast-icon"><i class="ti ' + icon + '"></i></div>' +
    '<div class="toast-message">' + msg + '</div>' +
    '<button class="toast-close" onclick="this.parentElement.remove()"><i class="ti ti-x"></i></button>';
  
  container.appendChild(toast);
  
  var timeout = type === 'error' ? 5000 : 3500;
  setTimeout(function() {
    if (toast.parentElement) {
      toast.remove();
    }
  }, timeout);
  
  return toast;
}

// ── Retry Logic (Exponential Backoff) ─────────
var RequestRetry = {
  maxRetries: 3,
  baseDelay: 1000,
  maxDelay: 10000,
  
  async: function(fetchPromise, retries) {
    retries = retries || 0;
    var self = this;
    
    return fetchPromise.catch(function(error) {
      if (retries < self.maxRetries) {
        var delay = Math.min(
          self.baseDelay * Math.pow(2, retries),
          self.maxDelay
        );
        
        showToast("Retrying in " + (delay / 1000) + "s...", 'info');
        
        return new Promise(function(resolve) {
          setTimeout(function() {
            resolve(self.async(fetchPromise, retries + 1));
          }, delay);
        });
      } else {
        throw error;
      }
    });
  },
  
  fetch: function(url, options, retries) {
    retries = retries || 0;
    var self = this;
    options = options || {};
    
    return fetch(url, options).then(function(response) {
      if (!response.ok) {
        if (response.status >= 500 && retries < self.maxRetries) {
          var delay = Math.min(
            self.baseDelay * Math.pow(2, retries),
            self.maxDelay
          );
          
          return new Promise(function(resolve) {
            setTimeout(function() {
              resolve(self.fetch(url, options, retries + 1));
            }, delay);
          });
        }
        throw new Error("HTTP " + response.status + ": " + response.statusText);
      }
      return response;
    }).catch(function(error) {
      if (retries < self.maxRetries && (error instanceof TypeError || error.message.includes('HTTP 5'))) {
        var delay = Math.min(
          self.baseDelay * Math.pow(2, retries),
          self.maxDelay
        );
        
        showToast("Connection error, retrying...", 'warning');
        
        return new Promise(function(resolve) {
          setTimeout(function() {
            resolve(self.fetch(url, options, retries + 1));
          }, delay);
        });
      }
      throw error;
    });
  }
};

// ── Progressive Enhancement ────────────────
var ProgressiveEnhancement = {
  supports: {
    fetch: typeof fetch !== 'undefined',
    eventStream: typeof EventSource !== 'undefined',
    formData: typeof FormData !== 'undefined'
  },
  
  fallback: function(feature) {
    console.log('Progressive enhancement: fallback for', feature);
    if (feature === 'fetch') {
      return new Error('Fetch API not supported. Please use a modern browser.');
    }
    return new Error(feature + ' not supported.');
  },
  
  init: function() {
    if (!this.supports.fetch) {
      showToast('⚠ Some features may not work. Please update your browser.', 'warning');
    }
  }
};

// ── Theme ──────────────────────────────────────
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
  
  ProgressiveEnhancement.init();
})();

// ── Skeleton Loaders ────────────────────────
function showSkeleton(containerId, count) {
  count = count || 3;
  var container = document.getElementById(containerId);
  if (!container) return;
  
  var html = '';
  for (var i = 0; i < count; i++) {
    html += '<div class="skeleton-card skeleton"></div>';
  }
  container.innerHTML = html;
}

function removeSkeleton(containerId) {
  var container = document.getElementById(containerId);
  if (!container) return;
  
  var skeletons = container.querySelectorAll('.skeleton-card');
  skeletons.forEach(function(el) {
    el.remove();
  });
}

// ── File upload ───────────────────────────────
function handleFile(input) {
  var file = input.files[0];
  if (!file) return;
  
  var chosen = document.getElementById("file-chosen");
  var btn    = document.getElementById("submit-btn");
  var title  = document.getElementById("drop-title");
  var sub    = document.getElementById("drop-sub");
  
  if (!file.name.endsWith('.csv')) {
    showToast('⚠ Only CSV files are supported', 'warning');
    input.value = '';
    return;
  }
  
  var maxSize = 52428800; // 50MB
  if (file.size > maxSize) {
    showToast('✗ File exceeds 50MB limit', 'error');
    input.value = '';
    return;
  }
  
  var kb = (file.size / 1024).toFixed(1);
  if (chosen) {
    chosen.style.display = "flex";
    chosen.innerHTML =
      '<i class="ti ti-file-spreadsheet"></i> ' +
      file.name + ' (' + kb + ' KB)';
  }
  if (btn) {
    btn.style.display = "inline-flex";
    btn.setAttribute('data-loading', 'false');
  }
  if (title) title.textContent = "✓ File ready!";
  if (sub) sub.textContent = "Click Analyse to start processing";
  
  showToast('✓ File selected: ' + file.name, 'success');
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
    
    if (!file) {
      showToast('✗ No file detected', 'error');
      return;
    }
    
    if (!file.name.endsWith(".csv")) {
      showToast('✗ Please drop a CSV file', 'error');
      return;
    }
    
    var inp = document.getElementById("file-input");
    if (!inp) return;
    
    var dt = new DataTransfer();
    dt.items.add(file);
    inp.files = dt.files;
    handleFile(inp);
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