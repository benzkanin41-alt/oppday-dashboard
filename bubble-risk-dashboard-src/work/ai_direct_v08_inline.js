
(function(){
  var dataEl = document.getElementById('ai-direct-data');
  if (!dataEl) return;
  var model = JSON.parse(dataEl.textContent);
  var NS = 'http://www.w3.org/2000/svg';
  var margin = {left: 54, right: 22, top: 22, bottom: 90};
  var width = 720;
  var height = 360;
  var resetDetail = "ชี้จุดบนกราฟหรือคลิกจุด เพื่อดูวันที่ ค่า และ source ของจุดนั้น";
  var domainStart = new Date(model.window_start + 'T00:00:00Z').getTime();
  var domainEnd = new Date(model.window_end + 'T00:00:00Z').getTime();

  function svgEl(name, attrs) {
    var el = document.createElementNS(NS, name);
    Object.keys(attrs || {}).forEach(function(key){ el.setAttribute(key, attrs[key]); });
    return el;
  }
  function fmt(value, unit) {
    var digits = Math.abs(value) >= 100 ? 0 : 2;
    return Number(value).toLocaleString(undefined, {maximumFractionDigits: digits}) + (unit ? ' ' + unit : '');
  }
  function xScale(time) {
    if (domainEnd === domainStart) return margin.left;
    return margin.left + (time - domainStart) / (domainEnd - domainStart) * (width - margin.left - margin.right);
  }
  function escapeHtml(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }
  function pointerInSvg(svg, event) {
    var pt = svg.createSVGPoint();
    pt.x = event.clientX;
    pt.y = event.clientY;
    var ctm = svg.getScreenCTM();
    return ctm ? pt.matrixTransform(ctm.inverse()) : null;
  }
  function nearest(points, local) {
    var best = null;
    points.forEach(function(point){
      var dx = point.x - local.x;
      var dy = point.y - local.y;
      var dist = Math.sqrt(dx * dx + dy * dy);
      if (!best || dist < best.dist) best = {point: point, dist: dist};
    });
    return best;
  }
  function setDetail(cardId, htmlText) {
    var detail = document.querySelector('[data-ai-detail="' + cardId + '"]');
    if (detail) detail.innerHTML = htmlText;
  }
  function detailHtml(point, unit) {
    var lines = [
      '<b>' + escapeHtml(point.series) + '</b>',
      'Date: ' + escapeHtml(point.date),
      'Value: ' + escapeHtml(fmt(point.value, unit))
    ];
    if (point.tag) lines.push('SEC tag: ' + escapeHtml(point.tag));
    if (point.form) lines.push('Filing: ' + escapeHtml(point.form) + (point.filed ? ' filed ' + escapeHtml(point.filed) : ''));
    if (point.accn) lines.push('Accession: ' + escapeHtml(point.accn));
    if (point.source) lines.push('Source: ' + escapeHtml(point.source));
    if (point.source_kind) lines.push('Source type: ' + escapeHtml(point.source_kind));
    return lines.join('<br>');
  }
  function showPoint(card, point, hoverLine) {
    hoverLine.setAttribute('x1', point.x);
    hoverLine.setAttribute('x2', point.x);
    hoverLine.style.display = 'block';
    setDetail(card.id, detailHtml(point, card.unit));
  }
  function drawCoverageRail(svg, card, allPoints) {
    var railY = height - 48;
    svg.appendChild(svgEl('line', {x1: margin.left, y1: railY, x2: width - margin.right, y2: railY, class: 'ai-window-rail'}));
    [model.window_start, model.window_end].forEach(function(d, idx){
      var x = idx ? width - margin.right : margin.left;
      svg.appendChild(svgEl('line', {x1: x, y1: railY - 8, x2: x, y2: railY + 8, class: 'ai-window-tick'}));
      var t = svgEl('text', {x: idx ? x - 66 : x, y: height - 14, class: 'ai-window-label'});
      t.textContent = d;
      svg.appendChild(t);
    });
    var label = svgEl('text', {x: margin.left, y: railY - 12, class: card.sparse ? 'ai-no-data-label' : 'ai-window-label'});
    label.textContent = card.sparse ? '2-year window: public data is sparse; dots are the sourced observations found' : '2-year data window';
    svg.appendChild(label);
    allPoints.forEach(function(point){
      svg.appendChild(svgEl('circle', {cx: point.x, cy: railY, r: 3.5, fill: point.color, class: 'ai-window-dot'}));
    });
  }
  function drawChart(card) {
    var holder = document.querySelector('[data-ai-chart="' + card.id + '"]');
    if (!holder) return;
    var svg = holder.querySelector('svg');
    svg.innerHTML = '';
    var values = [];
    card.series.forEach(function(series){
      series.points.forEach(function(point){
        var t = new Date(point.date + 'T00:00:00Z').getTime();
        if (t >= domainStart && t <= domainEnd) values.push(point.value);
      });
    });
    if (!values.length) return;
    var minY = Math.min.apply(null, values);
    var maxY = Math.max.apply(null, values);
    if (minY === maxY) { minY = minY * 0.9; maxY = maxY * 1.1 + 1; }
    var pad = (maxY - minY) * 0.14;
    minY = Math.max(0, minY - pad);
    maxY = maxY + pad;
    function yScale(value) {
      return height - margin.bottom - (value - minY) / (maxY - minY) * (height - margin.top - margin.bottom);
    }
    for (var i = 0; i <= 4; i++) {
      var y = margin.top + i * (height - margin.top - margin.bottom) / 4;
      svg.appendChild(svgEl('line', {x1: margin.left, y1: y, x2: width - margin.right, y2: y, class: 'ai-grid-line'}));
      var labelValue = maxY - i * (maxY - minY) / 4;
      var text = svgEl('text', {x: 8, y: y + 4, class: 'ai-axis-label'});
      text.textContent = fmt(labelValue, '');
      svg.appendChild(text);
    }
    var midDate = new Date((domainStart + domainEnd) / 2).toISOString().slice(0, 10);
    [model.window_start, midDate, model.window_end].forEach(function(d){
      var x = xScale(new Date(d + 'T00:00:00Z').getTime());
      var text = svgEl('text', {x: x - 28, y: height - 55, class: 'ai-axis-label'});
      text.textContent = d;
      svg.appendChild(text);
    });
    var hoverLine = svgEl('line', {x1: 0, y1: margin.top, x2: 0, y2: height - margin.bottom, class: 'ai-hover-line'});
    svg.appendChild(hoverLine);
    var allPoints = [];
    card.series.forEach(function(series){
      var points = series.points.map(function(point){
        var time = new Date(point.date + 'T00:00:00Z').getTime();
        return Object.assign({}, point, {
          series: series.name,
          color: series.color,
          time: time,
          x: xScale(time),
          y: yScale(point.value)
        });
      }).filter(function(point){ return point.time >= domainStart && point.time <= domainEnd; });
      if (points.length > 1) {
        var d = points.map(function(point, index){
          return (index ? 'L' : 'M') + point.x.toFixed(2) + ' ' + point.y.toFixed(2);
        }).join(' ');
        svg.appendChild(svgEl('path', {d: d, class: 'ai-series-line', stroke: series.color}));
      }
      points.forEach(function(point){
        allPoints.push(point);
        var circle = svgEl('circle', {cx: point.x, cy: point.y, r: 5.5, fill: series.color, class: 'ai-point', tabindex: '0'});
        circle.addEventListener('pointerenter', function(){ showPoint(card, point, hoverLine); });
        circle.addEventListener('click', function(event){ event.stopPropagation(); showPoint(card, point, hoverLine); });
        circle.addEventListener('keydown', function(event){
          if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); showPoint(card, point, hoverLine); }
        });
        svg.appendChild(circle);
      });
    });
    drawCoverageRail(svg, card, allPoints);
    svg.addEventListener('pointermove', function(event){
      var local = pointerInSvg(svg, event);
      if (!local) return;
      var hit = nearest(allPoints, local);
      if (hit && hit.dist < 32) showPoint(card, hit.point, hoverLine);
    });
    svg.addEventListener('pointerleave', function(){ hoverLine.style.display = 'none'; });
    svg.addEventListener('click', function(){ hoverLine.style.display = 'none'; setDetail(card.id, resetDetail); });
    var legend = document.querySelector('[data-ai-legend="' + card.id + '"]');
    if (legend) {
      legend.innerHTML = card.series.map(function(series){
        return '<span><i style="background:' + series.color + '"></i>' + escapeHtml(series.name) + '</span>';
      }).join('');
    }
  }
  model.groups.forEach(drawChart);
  document.querySelectorAll('.ai-observation-row').forEach(function(row){
    row.addEventListener('click', function(){
      var obs = JSON.parse(row.getAttribute('data-ai-observation'));
      var card = row.closest('[data-ai-card]');
      var id = card ? card.getAttribute('data-ai-card') : '';
      setDetail(id, '<b>' + escapeHtml(obs.metric || 'Observation') + '</b><br>Date: ' + escapeHtml(obs.date || '') + '<br>Value: ' + escapeHtml(obs.value || '') + '<br>Source: ' + escapeHtml(obs.source || ''));
    });
  });
})();
