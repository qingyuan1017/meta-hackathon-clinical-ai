"""Generate the synthetic blank CRF used by the SDTM demo."""

from pathlib import Path

from reportlab.pdfgen import canvas


OUTPUT = Path(__file__).with_name("blank-crf.pdf")


def main() -> None:
    pdf = canvas.Canvas(str(OUTPUT))
    pdf.setTitle("Synthetic blank CRF")
    pages = {
        "SYNTHETIC STUDY — DEMOGRAPHICS": [
            "Subject Identifier",
            "Informed Consent Date",
            "Birth Year",
            "Age",
            "Sex",
            "Race",
            "Ethnicity",
        ],
        "SYNTHETIC STUDY — ADVERSE EVENTS": [
            "Adverse Event Term",
            "Adverse Event Start Date",
            "Adverse Event End Date",
            "Severity",
            "Serious Event",
        ],
    }
    for title, fields in pages.items():
        pdf.setFont("Helvetica-Bold", 16)
        pdf.drawString(54, 760, title)
        pdf.setFont("Helvetica", 9)
        pdf.drawString(54, 742, "HACKATHON SAMPLE · NO PATIENT DATA")
        y = 690
        for label in fields:
            pdf.setFont("Helvetica-Bold", 11)
            pdf.drawString(54, y, label)
            pdf.line(54, y - 20, 540, y - 20)
            y -= 64
        pdf.showPage()
    pdf.save()
    print(f"Created {OUTPUT}")


if __name__ == "__main__":
    main()
