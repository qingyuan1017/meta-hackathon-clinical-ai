import json
import zipfile

from docx import Document
from lxml import etree
from openpyxl import load_workbook
from reportlab.pdfgen import canvas

from app.artifacts import add_manifest_and_bundle, render_clinical_document, render_edc, render_protocol, render_sdtm, render_tlf
from app.schemas import ClinicalDocument, DocumentSection, EDCDesign, EDCField, EDCForm, EDCVisit, Objective, SDTMDataset, SDTMPlan, SDTMVariable, StudySummary, TLFColumn, TLFPlan, TLFSpec


def test_protocol_and_bundle(tmp_path) -> None:
    result = StudySummary(study_title="Synthetic study", objectives=[Objective(objective="Assess efficacy")])
    paths = add_manifest_and_bundle(render_protocol(result, tmp_path), tmp_path, "protocol-extraction")
    bundle = next(path for path in paths if path.suffix == ".zip")
    with zipfile.ZipFile(bundle) as archive:
        assert "protocol-extraction.json" in archive.namelist()
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["workflow"] == "protocol-extraction"


def test_document_and_edc_files_are_readable(tmp_path) -> None:
    document = ClinicalDocument(document_type="SAP", title="Synthetic SAP", executive_summary="Summary", sections=[DocumentSection(heading="Methods", body="Draft methods")])
    document_paths = render_clinical_document(document, tmp_path)
    assert Document(next(path for path in document_paths if path.suffix == ".docx")).paragraphs[0].text == "Synthetic SAP"

    edc = EDCDesign(study_name="SYN-101", visits=[EDCVisit(name="Baseline")], forms=[EDCForm(form_id="DM", name="Demographics", fields=[EDCField(field_id="AGE", label="Age", data_type="integer")])])
    edc_paths = render_edc(edc, tmp_path)
    workbook = load_workbook(next(path for path in edc_paths if path.suffix == ".xlsx"))
    assert "Forms and Fields" in workbook.sheetnames


def test_sdtm_and_tlf_artifacts(tmp_path) -> None:
    crf = tmp_path / "blank.pdf"
    pdf = canvas.Canvas(str(crf))
    pdf.drawString(50, 750, "Age")
    pdf.save()
    sdtm = SDTMPlan(
        study_name="SYN-101",
        datasets=[SDTMDataset(domain="DM", description="Demographics", variables=[SDTMVariable(name="AGE", label="Age", data_type="Num", source_field="Age")])],
    )
    sdtm_paths = render_sdtm(sdtm, crf, tmp_path, ["r", "sas"])
    define_path = next(path for path in sdtm_paths if path.name == "define.xml")
    tree = etree.parse(str(define_path))
    assert tree.getroot().tag.endswith("ODM")
    assert (tmp_path / "annotated-crf.pdf").stat().st_size > 0

    tlf = TLFPlan(study_name="SYN-101", outputs=[TLFSpec(output_id="T-01", output_type="table", title="Disposition", columns=[TLFColumn(heading="Treatment")])])
    tlf_paths = render_tlf(tlf, tmp_path, ["r", "sas"])
    assert Document(next(path for path in tlf_paths if path.name == "tlf-shells.docx")).tables
    assert (tmp_path / "build-tlfs.R").is_file()
