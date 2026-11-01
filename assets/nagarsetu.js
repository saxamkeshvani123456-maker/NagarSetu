(() => {
  const esc = (value = '') => String(value).replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
  const pretty = value => String(value || 'reported').replaceAll('_', ' ').replace(/\b\w/g, char => char.toUpperCase());
  const statusName = value => ({ resolution_claimed: 'Resolution claimed', independently_verified: 'Independently verified', citizen_confirmed: 'Citizen confirmed · not independently verified', independently_not_verified: 'Independent review did not verify resolution', not_verified: 'Not verified', response_published: 'Response published', under_review: 'Under review' })[value] || pretty(value);
  const api = async path => {
    const response = await fetch(path);
    if (!response.ok) throw new Error(`Public record unavailable (${response.status})`);
    return response.json();
  };

  const tile = 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png';
  function makeMap(id, zoom) {
    if (!window.L || !document.getElementById(id)) return null;
    const map = L.map(id, { scrollWheelZoom: false }).setView([22.5, 79], zoom);
    L.tileLayer(tile, { maxZoom: 19, attribution: '&copy; OpenStreetMap contributors' }).addTo(map);
    return map;
  }
  const hero = makeMap('hero-map', 4);
  const main = makeMap('incident-map', 5);
  const iconColors = { reported: '#e9a464', in_progress: '#3baea0', under_review: '#3baea0', response_published: '#4da99a', resolution_claimed: '#d98b50', independently_verified: '#087d71', resolved: '#778a93' };

  function addMarkers(map, incidents) {
    if (!map) return;
    if (map._nagarMarkers) map._nagarMarkers.forEach(marker => marker.remove());
    map._nagarMarkers = [];
    const points = [];
    incidents.forEach(incident => {
      if (!Number.isFinite(Number(incident.lat)) || !Number.isFinite(Number(incident.lng))) return;
      const color = iconColors[incident.status] || iconColors.reported;
      const marker = L.circleMarker([incident.lat, incident.lng], { radius: 7, fillColor: color, color: '#fff', weight: 2, fillOpacity: .95 }).addTo(map);
      marker.bindPopup(`<div class="pop-title">${esc(incident.title)}</div><div class="pop-meta">${esc(incident.category)} · ${esc(incident.address)}<br>${esc(statusName(incident.status))}</div><a class="pop-link" href="/incident.html?id=${encodeURIComponent(incident.tracking_id)}">Open public record →</a>`);
      map._nagarMarkers.push(marker);
      points.push([incident.lat, incident.lng]);
    });
    if (points.length) map.fitBounds(points, { padding: [28, 28], maxZoom: 13 });
  }

  const number = value => new Intl.NumberFormat('en-IN').format(value || 0);
  async function load() {
    const [overview, all] = await Promise.all([api('/api/public/overview'), api('/api/public/incidents')]);
    const values = [overview.counts.reports, overview.counts.unresolved, overview.counts.recurring, overview.counts.official_responses, overview.counts.resolution_claimed, overview.counts.independently_verified];
    const labels = ['ISSUES REPORTED', 'STILL UNRESOLVED', 'RECURRING LOCATIONS', 'OFFICIAL RESPONSES', 'RESOLUTION CLAIMED', 'INDEPENDENTLY VERIFIED'];
    const notes = ['Reports stored in this installation', 'Reported or in progress', 'More than one report or repeat reopening', 'Source-linked statements', 'Awaiting evidence review', 'Evidence-backed records'];
    const metricBox = document.getElementById('metrics');
    if (metricBox) metricBox.innerHTML = values.map((value, index) => `<article><span>${labels[index]}</span><strong>${number(value)}</strong><small>${notes[index]}</small></article>`).join('');
    const categoryBox = document.getElementById('category-list');
    if (categoryBox) {
      if (!overview.categories.length) categoryBox.innerHTML = '<div class="empty-state">No reports yet. Category counts will appear as residents submit issues.</div>';
      else {
        const max = Math.max(...overview.categories.map(item => item.count));
        categoryBox.innerHTML = overview.categories.map(item => `<div class="category-item"><span>${esc(item.category)}</span><b>${number(item.count)}</b><div class="bar"><i style="width:${Math.round(item.count / max * 100)}%"></i></div></div>`).join('');
      }
    }
    const recent = document.getElementById('recent-list');
    if (recent) {
      if (!all.incidents.length) recent.innerHTML = '<div class="empty-state">No citizen reports have been submitted yet. Public incidents will appear here when they exist.</div>';
      else recent.innerHTML = all.incidents.slice(0, 5).map(item => `<a class="recent-row" href="/incident.html?id=${encodeURIComponent(item.tracking_id)}"><span class="recent-pin">⌖</span><span><strong>${esc(item.title)}</strong><small>${esc(item.category)} · ${esc(item.address)} · ${new Date(item.created_at).toLocaleDateString()}</small></span><span class="status">${esc(statusName(item.status))}</span></a>`).join('');
    }
    const total = document.getElementById('map-total');
    if (total) total.textContent = `${number(all.incidents.length)} ${all.incidents.length === 1 ? 'REPORT' : 'REPORTS'}`;
    addMarkers(hero, all.incidents);
    addMarkers(main, all.incidents);
    const categoryFilter = document.getElementById('category-filter');
    if (categoryFilter) {
      const categories = [...new Set(all.incidents.map(item => item.category))].sort();
      categoryFilter.innerHTML = '<option value="">All categories</option>' + categories.map(value => `<option value="${esc(value)}">${esc(value)}</option>`).join('');
      categoryFilter.onchange = filterIncidents;
      document.getElementById('status-filter').onchange = filterIncidents;
    }
    if (document.getElementById('public-incidents')) renderPublic(all.incidents);
    if (document.getElementById('incident-detail')) await loadIncident();
  }

  function renderPublic(items) {
    const target = document.getElementById('public-incidents');
    if (!target) return;
    if (!items.length) {
      target.innerHTML = '<div class="empty-state">There are no public incidents yet. Reports appear here after residents submit them.</div>';
      return;
    }
    target.innerHTML = items.map(item => `<a class="recent-row" href="/incident.html?id=${encodeURIComponent(item.tracking_id)}"><span class="recent-pin">⌖</span><span><strong>${esc(item.title)}</strong><small>${esc(item.category)} · ${esc(item.address)} · ${new Date(item.created_at).toLocaleDateString()}</small></span><span class="status">${esc(statusName(item.status))}</span></a>`).join('');
  }

  async function filterIncidents() {
    const query = new URLSearchParams();
    const category = document.getElementById('category-filter')?.value;
    const status = document.getElementById('status-filter')?.value;
    if (category) query.set('category', category);
    if (status) query.set('status', status);
    try {
      const result = await api('/api/public/incidents?' + query);
      addMarkers(main, result.incidents);
      if (document.getElementById('public-incidents')) renderPublic(result.incidents);
    } catch { /* the page-level connection state remains visible */ }
  }

  function outcomeLabel(value) {
    return ({ independently_verified: 'Independently verified', not_verified: 'Not verified', citizen_confirmed_not_independently_verified: 'Citizen confirmed · independent review pending', resolution_claimed_awaiting_verification: 'Resolution claimed · review pending', deadline_passed_no_resolution_recorded: 'Published deadline passed · no resolution claim recorded', awaiting_follow_up: 'Awaiting follow-up evidence' })[value] || 'No outcome recorded';
  }

  function renderCommitment(commitment) {
    const evidenceCount = (commitment.subsequent_evidence || []).length;
    const claims = commitment.subsequent_resolution_claims || [];
    const latestReview = (commitment.subsequent_reviews || []).slice(-1)[0];
    return `<article class="commitment-card">
      <div class="commitment-card-head"><span class="record-label">PUBLISHED COMMITMENT</span><span class="outcome-pill">${esc(outcomeLabel(commitment.reality_status))}</span></div>
      <h3>${esc(commitment.promised_action || 'Published commitment')}</h3>
      <p class="source-quote">${esc(commitment.statement)}</p>
      <div class="commitment-meta"><span>Authority <b>${esc(commitment.promised_by || 'Named in source')}</b></span><span>Published <b>${esc(new Date(commitment.published_at).toLocaleDateString())}</b></span><span>Deadline <b>${commitment.promised_by_date ? esc(new Date(`${commitment.promised_by_date}T00:00:00`).toLocaleDateString()) : 'No date published'}</b></span></div>
      <div class="reality-check"><div class="reality-title"><span>RECORDED REALITY</span><b>${evidenceCount} later evidence item${evidenceCount === 1 ? '' : 's'}</b></div><p>${esc(outcomeLabel(commitment.reality_status))}. ${claims.length ? `Resolution claim recorded: ${esc(claims[claims.length - 1].note)}` : 'No later resolution claim is recorded.'} ${latestReview ? `Latest review: ${esc(latestReview.evidence)}` : ''}</p></div>
      <a class="source-link" href="${esc(commitment.source_url)}" target="_blank" rel="noopener noreferrer">${esc(commitment.source_name)} · view original source ↗</a>
      <small class="recorded-at">Published ${esc(commitment.published_at)} · added to NagarSetu ${esc(new Date(commitment.recorded_at).toLocaleString())}</small>
    </article>`;
  }

  function renderResponse(response) {
    return `<article class="response-card"><div class="response-card-head"><span class="record-label">AUTHORITY RESPONSE</span><span>${esc(new Date(response.published_at).toLocaleDateString())}</span></div><p>${esc(response.statement)}</p><div class="response-meta">${response.promised_by ? `Published by ${esc(response.promised_by)} · ` : ''}${esc(response.source_name)} <a href="${esc(response.source_url)}" target="_blank" rel="noopener noreferrer">Original source ↗</a></div></article>`;
  }

  function renderEvidence(evidence) {
    const typeLabel = evidence.image_role === 'resolution' ? 'Authority resolution evidence' : evidence.image_role === 'replacement' ? 'Citizen follow-up evidence' : 'Original citizen evidence';
    return `<article class="evidence-card"><a class="evidence-image" href="${esc(evidence.url)}" target="_blank" rel="noopener noreferrer"><img src="${esc(evidence.url)}" alt="${esc(typeLabel)}" loading="lazy"></a><div class="evidence-body"><span class="evidence-type">${esc(typeLabel)}</span><h3>${esc(evidence.report_title)}</h3><p>${esc(evidence.original_filename)} · ${esc(evidence.final_authenticity_state || 'not reviewed')}</p><div class="evidence-foot"><time>${esc(new Date(evidence.created_at).toLocaleString())}</time><span>${esc(evidence.width || '?')} × ${esc(evidence.height || '?')}</span></div><code>SHA-256 ${esc(evidence.sha256)}</code></div></article>`;
  }

  function renderIncidentTimeline(events, claims, verifications) {
    const baseEvents = events.filter(event => !['resolution_claim', 'verification'].includes(event.event_type));
    const combined = [...baseEvents.map(event => ({ ...event, kind: 'event' })), ...claims.map(claim => ({ event_type: 'resolution_claim', title: 'Resolution claimed', body: claim.note, actor_type: 'authority', created_at: claim.created_at, kind: 'claim' })), ...verifications.map(review => ({ event_type: 'verification', title: review.decision === 'verified' ? 'Resolution independently verified' : 'Resolution not verified', body: review.evidence, actor_type: 'reviewer', created_at: review.created_at, source_url: review.evidence_url, kind: 'review' }))].sort((a, b) => a.created_at.localeCompare(b.created_at));
    if (!combined.length) return '<div class="promise-empty">The civic memory timeline will fill as reports, official records and follow-up evidence are added.</div>';
    return combined.map((event, index) => `<article class="memory-event"><span class="memory-index">${String(index + 1).padStart(2, '0')}</span><span class="memory-node ${event.actor_type === 'official' || event.actor_type === 'authority' ? 'orange' : ''}"></span><div><div class="memory-meta">${esc(pretty(event.actor_type))} <time>${esc(new Date(event.created_at).toLocaleString())}</time></div><h3>${esc(event.title)}</h3><p>${esc(event.body)}</p>${event.source_name ? `<a href="${esc(event.source_url)}" target="_blank" rel="noopener noreferrer">${esc(event.source_name)} · original source ↗</a>` : ''}${event.source_url && !event.source_name ? `<a href="${esc(event.source_url)}" target="_blank" rel="noopener noreferrer">Evidence source ↗</a>` : ''}</div></article>`).join('');
  }

  async function loadIncident() {
    const id = new URLSearchParams(location.search).get('id');
    const root = document.getElementById('incident-detail');
    if (!id) {
      root.innerHTML = '<div class="empty-state">Choose an incident from the public list.</div>';
      return;
    }
    try {
      const incident = await api('/api/public/incidents/' + encodeURIComponent(id));
      document.title = `${incident.title} — NagarSetu`;
      const statements = incident.official_statements || [];
      const commitments = statements.filter(record => record.record_type === 'commitment');
      const responses = statements.filter(record => record.record_type !== 'commitment');
      const claims = incident.resolution_claims || [];
      const reviews = incident.verification || [];
      const evidence = incident.evidence || [];
      const verified = incident.status === 'independently_verified';
      const statusText = verified ? 'Independently verified' : incident.status === 'citizen_confirmed' ? 'Citizen confirmed · no independent review' : incident.status === 'not_verified' ? 'Resolution not verified' : claims.length ? 'Resolution claimed · pending review' : statements.length ? 'Authority response published' : statusName(incident.status);
      const commitmentsMarkup = commitments.length ? commitments.map(renderCommitment).join('') : '<div class="promise-empty"><b>No published commitment has been recorded.</b><span>When an authority publishes a promise, the source and any stated deadline will appear here.</span></div>';
      const responsesMarkup = responses.length ? responses.map(renderResponse).join('') : '<div class="promise-empty"><b>No authority response is on record.</b><span>NagarSetu does not invent official updates. A response appears after its source is added.</span></div>';
      const evidenceMarkup = evidence.length ? evidence.map(renderEvidence).join('') : '<div class="promise-empty"><b>No photographs are attached yet.</b><span>Citizen and authority evidence will appear with its upload time when submitted.</span></div>';
      const finalReview = reviews.length ? reviews[reviews.length - 1] : null;
      const reviewMarkup = finalReview ? `<div class="verification-result ${finalReview.decision === 'verified' ? 'is-verified' : 'is-open'}"><span class="verification-symbol">${finalReview.decision === 'verified' ? '✓' : '!'}</span><div><small>FINAL RECORDED REVIEW · ${esc(new Date(finalReview.created_at).toLocaleString())}</small><h3>${finalReview.decision === 'verified' ? 'Resolution independently verified' : 'Resolution not verified'}</h3><p>${esc(finalReview.evidence)}</p><p class="reviewer-note">Reviewed by a separate ${esc(finalReview.reviewer_role || 'authorized')} reviewer; reviewer contact details are withheld.</p>${finalReview.evidence_url ? `<a href="${esc(finalReview.evidence_url)}" target="_blank" rel="noopener noreferrer">Review evidence source ↗</a>` : ''}</div></div>` : `<div class="verification-result is-open"><span class="verification-symbol">${incident.status === 'citizen_confirmed' ? '✓' : '…'}</span><div><small>${incident.status === 'citizen_confirmed' ? 'CITIZEN FOLLOW-UP RECORDED' : 'FINAL RECORDED REVIEW'}</small><h3>${incident.status === 'citizen_confirmed' ? 'Citizen confirmed the reported fix' : incident.status === 'not_verified' ? 'Citizen did not confirm the reported fix' : claims.length ? 'A resolution claim is awaiting review' : 'No resolution has been independently verified'}</h3><p>${incident.status === 'citizen_confirmed' ? 'The original reporter approved the repair. This is a citizen confirmation; no separate independent review is recorded.' : incident.status === 'not_verified' ? 'The original reporter rejected the repair and the issue was reopened.' : 'Verification remains pending until a reviewer records the evidence and decision. A promise or uploaded photo alone does not mark an issue as solved.'}</p></div></div>`;
      root.innerHTML = `<section class="incident-hero"><div class="incident-hero-kicker">PUBLIC INCIDENT · ${esc(incident.tracking_id)}</div><div class="incident-hero-row"><div><h1>${esc(incident.title)}</h1><p>${esc(incident.description)}</p></div><span class="incident-status ${verified ? 'verified' : ''}"><i></i>${esc(statusText)}</span></div><div class="incident-facts"><span>${esc(incident.category)}</span><span>⌖ ${esc(incident.address)}</span><span>Reported ${esc(new Date(incident.created_at).toLocaleString())}</span><span>${evidence.length} evidence item${evidence.length === 1 ? '' : 's'} in this incident</span></div><div class="progress-rail"><span class="done">01 <b>Reported</b></span><i></i><span class="${statements.length ? 'done' : ''}">02 <b>Authority record</b></span><i></i><span class="${claims.length ? 'done' : ''}">03 <b>Resolution claim</b></span><i></i><span class="${verified ? 'done' : ''}">04 <b>Verified outcome</b></span></div></section>
      <section class="promise-reality-heading"><div><div class="eyebrow">THE ACCOUNTABILITY RECORD</div><h2>Promise <em>vs</em> reality</h2></div><p>Every commitment is tied to a published source. Outcomes reflect recorded evidence and review decisions.</p></section>
      <section class="promise-reality-grid"><div class="promise-column"><div class="column-heading"><span class="column-number">01</span><div><small>WHAT WAS PUBLISHED</small><h2>Promises & timelines</h2></div></div>${commitmentsMarkup}</div><div class="reality-column"><div class="column-heading"><span class="column-number">02</span><div><small>WHAT THE RECORD SHOWS</small><h2>Reality & verification</h2></div></div>${reviewMarkup}<div class="claim-list">${claims.length ? claims.map(claim => `<div class="claim-row"><span>RESOLUTION CLAIM</span><p>${esc(claim.note)}</p><small>Submitted ${esc(new Date(claim.created_at).toLocaleString())} · ${esc(pretty(claim.status))}</small></div>`).join('') : '<div class="claim-row muted">No resolution claim has been recorded.</div>'}</div></div></section>
      <section class="response-section"><div class="section-kicker">AUTHORITY UPDATES</div><h2>Responses on the record</h2><div class="response-grid">${responsesMarkup}</div></section>
      <section class="evidence-section"><div class="evidence-section-head"><div><div class="section-kicker">EVIDENCE LOG · ${evidence.length} ITEMS</div><h2>What changed over time</h2><p>Original reports and later uploads from every report in this incident cluster. Timestamps and image checks are shown as recorded.</p></div><span class="source-badge">CITIZEN + AUTHORITY RECORDS</span></div><div class="evidence-grid">${evidenceMarkup}</div></section>
      <section class="memory-section"><div class="section-kicker">CIVIC MEMORY</div><h2>The full incident timeline</h2><div class="memory-list">${renderIncidentTimeline(incident.timeline || [], claims, reviews)}</div></section>`;
    } catch {
      root.innerHTML = '<div class="empty-state">This incident record is unavailable.</div>';
    }
  }

  load().catch(() => {
    const recent = document.getElementById('recent-list');
    if (recent) recent.innerHTML = '<div class="empty-state">Could not connect to the NagarSetu public record. Start the application server and reload.</div>';
    const root = document.getElementById('incident-detail');
    if (root) root.innerHTML = '<div class="empty-state">Could not connect to the incident record.</div>';
  });
})();
