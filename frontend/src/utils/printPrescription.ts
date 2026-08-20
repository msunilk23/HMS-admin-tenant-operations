import type { Visit, Prescription, Consultation } from '@/types/common'

const FREQUENCY_LABELS: Record<string, string> = {
  OD:  'Once Daily',
  BD:  'Twice Daily',
  TID: 'Three Times a Day',
  QID: 'Four Times a Day',
  SOS: 'As Needed',
  QHS: 'Every Night at Bedtime',
  Q4H: 'Every 4 Hours',
  Q6H: 'Every 6 Hours',
  Q8H: 'Every 8 Hours',
}

function expandFrequency(freq: string): string {
  return FREQUENCY_LABELS[freq] ?? freq
}

export function printPrescription(
  visit: Visit,
  prescription: Prescription | null,
  consultation: Consultation | null,
  hospitalName: string,
) {
  const date = new Date().toLocaleDateString('en-IN', { day: '2-digit', month: 'long', year: 'numeric' })
  const visitDate = new Date(visit.created_at).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' })

  const diagnosisStr = consultation?.diagnosis_icd10?.length
    ? consultation.diagnosis_icd10.map(d => `${d.code}${d.description ? ' — ' + d.description : ''}`).join(', ')
    : ''

  const medicinesHtml = (prescription?.medicines?.length ?? 0) > 0
    ? `<div class="section">
        <div class="section-title">Medicines</div>
        ${prescription!.medicines.map((m: any, i: number) => `
          <div class="item-row">
            <span class="item-num">${i + 1}.</span>
            <div>
              <strong>${m.name}</strong>
              <div class="medicine-detail">${[m.dose || m.dosage, m.route, expandFrequency(m.frequency), m.duration].filter(Boolean).join(' · ')}${(m.instructions || m.notes) ? ' · <em>' + (m.instructions || m.notes) + '</em>' : ''}</div>
            </div>
          </div>`).join('')}
      </div>`
    : ''

  const labHtml = (prescription?.lab_tests?.length ?? 0) > 0
    ? `<div class="section">
        <div class="section-title">Lab Tests</div>
        ${prescription!.lab_tests!.map((t: any, i: number) => `
          <div class="item-row">
            <span class="item-num">${i + 1}.</span>
            <span>${t.test_name}${t.notes ? ` <span class="note">(${t.notes})</span>` : ''}</span>
          </div>`).join('')}
      </div>`
    : ''

  const consultHtml = consultation
    ? `<div class="section">
        <div class="section-title">Consultation Notes</div>
        ${consultation.chief_complaint ? `<div class="field-row"><span class="field-label">Chief Complaint:</span><span>${consultation.chief_complaint}</span></div>` : ''}
        ${consultation.history ? `<div class="field-row"><span class="field-label">History:</span><span>${consultation.history}</span></div>` : ''}
        ${consultation.examination ? `<div class="field-row"><span class="field-label">Examination:</span><span>${consultation.examination}</span></div>` : ''}
        ${diagnosisStr ? `<div class="field-row"><span class="field-label">Diagnosis:</span><span>${diagnosisStr}</span></div>` : ''}
        ${consultation.notes ? `<div class="field-row"><span class="field-label">Notes:</span><span>${consultation.notes}</span></div>` : ''}
        ${consultation.follow_up_date ? `<div class="field-row"><span class="field-label">Follow-up:</span><span>${new Date(consultation.follow_up_date).toLocaleDateString('en-IN')}</span></div>` : ''}
      </div>`
    : ''

  const instructionsHtml = prescription?.instructions
    ? `<div class="section">
        <div class="section-title">Instructions to Patient</div>
        <div class="instructions-box">${prescription.instructions}</div>
      </div>`
    : ''

  const html = `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <title>Prescription — ${visit.patient_name ?? 'Patient'}</title>
  <style>
    @page { size: A4 portrait; margin: 18mm 15mm 20mm 15mm; }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: Arial, Helvetica, sans-serif; font-size: 11pt; color: #111; background: #fff; }

    /* ── Header ── */
    .header { display: flex; align-items: flex-start; justify-content: space-between; padding-bottom: 10px; border-bottom: 2.5px solid #222; margin-bottom: 14px; }
    .header-left { flex: 1; }
    .header-center { flex: 2; text-align: center; }
    .header-right { flex: 1; text-align: right; font-size: 9.5pt; color: #444; line-height: 1.6; white-space: nowrap; }
    .hospital-name { font-size: 20pt; font-weight: 900; text-transform: uppercase; letter-spacing: 2px; }
    .hospital-sub { font-size: 9.5pt; color: #555; margin-top: 2px; letter-spacing: 0.5px; }

    /* ── Title ── */
    .doc-title { text-align: center; font-size: 12pt; font-weight: bold; letter-spacing: 3px; text-transform: uppercase; margin-bottom: 12px; color: #333; }

    /* ── Patient meta ── */
    .meta-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 4px 24px; margin-bottom: 12px; font-size: 10.5pt; }
    .meta-row { display: flex; gap: 6px; }
    .meta-label { font-weight: bold; min-width: 95px; color: #333; }
    .meta-value { color: #111; }

    hr.dashed { border: none; border-top: 1px dashed #bbb; margin: 10px 0; }

    /* ── Sections ── */
    .section { margin: 12px 0; }
    .section-title { font-size: 10pt; font-weight: bold; text-transform: uppercase; letter-spacing: 1px; color: #444; border-bottom: 1px solid #ccc; padding-bottom: 3px; margin-bottom: 8px; }

    /* Consultation */
    .field-row { display: flex; gap: 8px; margin: 5px 0; font-size: 10.5pt; }
    .field-label { font-weight: bold; min-width: 120px; color: #333; }

    /* Medicines */
    .item-row { display: flex; gap: 8px; margin: 6px 0; align-items: flex-start; font-size: 10.5pt; }
    .item-num { min-width: 18px; font-weight: bold; }
    .medicine-detail { font-size: 10pt; color: #444; margin-top: 1px; }
    .note { color: #666; font-size: 10pt; }

    /* Instructions */
    .instructions-box { background: #f8f8f8; border: 1px solid #ddd; border-radius: 3px; padding: 8px 12px; font-size: 10.5pt; line-height: 1.5; }

    /* Footer */
    .footer { margin-top: 40px; display: flex; justify-content: flex-end; page-break-inside: avoid; }
    .signature-box { text-align: center; width: 180px; }
    .signature-line { border-top: 1px solid #333; margin-bottom: 5px; }
    .signature-name { font-weight: bold; font-size: 10.5pt; }
    .signature-sub { font-size: 9.5pt; color: #555; }
  </style>
</head>
<body>

  <!-- Header -->
  <div class="header">
    <div class="header-left"></div>
    <div class="header-center">
      <div class="hospital-name">${hospitalName}</div>
      <div class="hospital-sub">OPD Prescription</div>
    </div>
    <div class="header-right">
      Date: ${date}
    </div>
  </div>

  <div class="doc-title">Prescription</div>

  <!-- Patient / Doctor meta -->
  <div class="meta-grid">
    <div class="meta-row"><span class="meta-label">Patient:</span><span class="meta-value">${visit.patient_name ?? '—'}</span></div>
    <div class="meta-row"><span class="meta-label">Doctor:</span><span class="meta-value">${visit.doctor_name ? 'Dr. ' + visit.doctor_name : '—'}</span></div>
    <div class="meta-row"><span class="meta-label">Department:</span><span class="meta-value">${visit.department_name || '—'}</span></div>
    <div class="meta-row"><span class="meta-label">Visit Date:</span><span class="meta-value">${visitDate}</span></div>
  </div>

  <hr class="dashed"/>

  ${consultHtml}
  ${consultHtml ? '<hr class="dashed"/>' : ''}
  ${medicinesHtml}
  ${medicinesHtml && labHtml ? '<hr class="dashed"/>' : ''}
  ${labHtml}
  ${instructionsHtml ? '<hr class="dashed"/>' : ''}
  ${instructionsHtml}

  <!-- Signature -->
  <div class="footer">
    <div class="signature-box">
      <div class="signature-line"></div>
      <div class="signature-name">Dr. ${visit.doctor_name ?? '—'}</div>
      <div class="signature-sub">Doctor's Signature</div>
    </div>
  </div>

</body>
</html>`

  const win = window.open('', '_blank', 'width=794,height=1123,menubar=no,toolbar=no')
  if (!win) {
    alert('Pop-up blocked. Please allow pop-ups for this site to print.')
    return
  }
  win.document.write(html)
  win.document.close()
  win.focus()
  win.addEventListener('afterprint', () => win.close())
  win.print()
}
