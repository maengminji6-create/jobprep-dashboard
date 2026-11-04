// 공통 스크립트: 차트 기본값, 알림 토스트, 첫 화면 시계, 코멘트 서랍, 스크롤 모션, 점수 링, AI 버튼 상태
(function () {
  if (window.Chart) {
    // 선명하게: 화면 배율이 낮아도 최소 2배 해상도로 그리고, 글씨는 12px · 진한 회색
    Chart.defaults.devicePixelRatio = Math.max(2, window.devicePixelRatio || 1);
    Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
    Chart.defaults.font.size = 12;
    Chart.defaults.color = "#5c5e64";
    Chart.defaults.borderColor = "#d6d8dc";
    Chart.defaults.plugins.legend.labels.boxWidth = 10;
    Chart.defaults.plugins.legend.labels.usePointStyle = true;
    Chart.defaults.plugins.tooltip.padding = 10;
    Chart.defaults.plugins.tooltip.cornerRadius = 10;
    Chart.defaults.elements.bar.borderRadius = 6;
  }
  // 차트 공통 색: 슬레이트 블루 · 연한 슬레이트 · 더스티 로즈 · 세이지 — app.css 토큰과 맞춤
  window.PALETTE = { main: "#4e6b8a", light: "#bfcddb", coral: "#c98d87", sage: "#7f9f8a",
                     mainFill: "rgba(78,107,138,.18)", grid: "#d6d8dc", label: "#5c5e64", labelOn: "#2b2c30" };

  // 코멘트: 카드 안에서 펼치면 같은 줄 카드가 모두 늘어나므로, 오른쪽 서랍으로 띄움.
  // 내용은 복사하지 않고 옮겼다가 닫을 때 제자리로 돌려놓음(AI 버튼 등 동작 유지). dialog 가 없으면 그냥 펼침
  if (window.HTMLDialogElement) {
    var drawer = document.createElement("dialog"), home = null;
    drawer.className = "drawer";
    drawer.setAttribute("aria-labelledby", "drawer-title");
    drawer.innerHTML = '<div class="drawer-inner"><div class="drawer-head"><div><small>자소서 코멘트</small>' +
      '<h3 id="drawer-title"></h3></div><button type="button" class="round-btn sm" aria-label="닫기">×</button></div>' +
      '<div class="drawer-body"></div></div>';
    document.body.appendChild(drawer);
    var body = drawer.querySelector(".drawer-body");
    drawer.querySelector("button").addEventListener("click", function () { drawer.close(); });
    drawer.addEventListener("click", function (e) { if (e.target === drawer) drawer.close(); });  // 바깥(배경) 누르면 닫힘
    drawer.addEventListener("close", function () {
      if (home) { while (body.firstChild) home.appendChild(body.firstChild); home = null; }
    });
    document.querySelectorAll("details.cmt").forEach(function (d) {
      d.querySelector("summary").addEventListener("click", function (e) {
        e.preventDefault();
        if (drawer.open) drawer.close();
        var card = d.closest(".card"), title = card && card.querySelector("h3");
        drawer.querySelector("h3").textContent = title ? title.textContent.trim() : "코멘트";
        home = d;
        Array.prototype.slice.call(d.children).forEach(function (c) { if (c.tagName !== "SUMMARY") body.appendChild(c); });
        drawer.showModal();
      });
    });
  }

  // 첫 화면 시계 타일: 지금 시각 바늘 · 오늘 날짜(MM/DD)
  document.querySelectorAll("[data-clock]").forEach(function (clock) {
    function tick() {
      var d = new Date();
      clock.querySelector(".h").setAttribute("transform", "rotate(" + (d.getHours() % 12 * 30 + d.getMinutes() / 2) + " 50 50)");
      clock.querySelector(".m").setAttribute("transform", "rotate(" + d.getMinutes() * 6 + " 50 50)");
      document.querySelectorAll("[data-today]").forEach(function (el) {
        el.textContent = String(d.getMonth() + 1).padStart(2, "0") + "/" + String(d.getDate()).padStart(2, "0");
      });
    }
    tick();
    setInterval(tick, 30000);
  });

  // 복사 버튼(data-copy="#대상")
  document.querySelectorAll("[data-copy]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var el = document.querySelector(btn.dataset.copy);
      if (!el || !navigator.clipboard) return;
      navigator.clipboard.writeText(el.textContent.trim()).then(function () { btn.textContent = "복사됨"; });
    });
  });

  var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // 알림 토스트: 5초 뒤(오류는 9초) 또는 누르면 사라짐
  document.querySelectorAll(".toasts .flash").forEach(function (t) {
    function hide() { t.classList.add("out"); setTimeout(function () { t.remove(); }, 450); }
    t.addEventListener("click", hide);
    setTimeout(hide, t.classList.contains("error") ? 9000 : 5000);
  });

  // 화면에 들어오면 섹션이 말랑하게 떠오르고, 점수 링이 차오름
  var grids = document.querySelectorAll(".reveal .grid, .reveal .exp-grid");
  grids.forEach(function (g) {
    Array.prototype.forEach.call(g.children, function (c, i) { c.style.setProperty("--i", Math.min(i, 8)); });
  });
  var targets = document.querySelectorAll(".reveal, .ring");
  if (!("IntersectionObserver" in window) || reduce) {
    targets.forEach(function (t) { t.classList.add("in"); });
  } else {
    var fired = false;
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (en.isIntersecting) { fired = true; en.target.classList.add("in"); io.unobserve(en.target); }
      });
    }, { threshold: 0.12, rootMargin: "0px 0px -40px 0px" });
    targets.forEach(function (t) { io.observe(t); });
    // 관찰이 동작하지 않는 환경(백그라운드 탭·미리보기 등)에서도 내용이 숨겨진 채 남지 않게:
    // 스크롤 위치로 한 번 더 확인하고, 그래도 안 되면 2.5초 뒤 모두 표시
    function check() {
      var h = window.innerHeight || 800;
      targets.forEach(function (t) {
        if (!t.classList.contains("in") && t.getBoundingClientRect().top < h * 0.92) t.classList.add("in");
      });
    }
    window.addEventListener("scroll", check, { passive: true });
    window.addEventListener("resize", check);
    setTimeout(check, 300);
    setTimeout(function () { if (!fired) targets.forEach(function (t) { t.classList.add("in"); }); else check(); }, 2500);
  }

  // 섹션 바로가기: 지금 보고 있는 섹션을 강조
  var navLinks = document.querySelectorAll(".section-nav a[href^='#']");
  if (navLinks.length && "IntersectionObserver" in window) {
    var byId = {};
    navLinks.forEach(function (a) { byId[a.getAttribute("href").slice(1)] = a; });
    var spy = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (en.isIntersecting && byId[en.target.id]) {
          navLinks.forEach(function (a) { a.classList.remove("on"); });
          byId[en.target.id].classList.add("on");
        }
      });
    }, { rootMargin: "-40% 0px -55% 0px" });
    Object.keys(byId).forEach(function (id) { var el = document.getElementById(id); if (el) spy.observe(el); });
  }

  // 오래 걸리는 제출 버튼(data-busy): 누르면 잠그고 진행 문구 표시
  document.querySelectorAll("button[data-busy]").forEach(function (b) {
    if (b.form) b.form.addEventListener("submit", function () { b.disabled = true; b.textContent = b.dataset.busy; });
  });

  // AI 요청은 몇 초~수십 초 걸리므로 버튼을 '작성 중'으로 바꿈
  document.querySelectorAll("[data-ai-form]").forEach(function (f) {
    f.addEventListener("submit", function () {
      var b = f.querySelector("button");
      b.disabled = true;
      b.textContent = "✦ AI가 분석하는 중… (최대 1분)";
    });
  });
})();
