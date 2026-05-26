import os
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

def create_resume_pdf():
    pdf_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_resume.pdf")
    
    # Initialize ReportLab letter canvas
    c = canvas.Canvas(pdf_path, pagesize=letter)
    width, height = letter
    
    # Write professional text blocks
    c.setFont("Helvetica-Bold", 20)
    c.drawString(50, height - 50, "Nicholas Anderson - Resume CV")
    
    c.setFont("Helvetica-Bold", 12)
    c.drawString(50, height - 80, "Contact Information:")
    c.setFont("Helvetica", 10)
    c.drawString(50, height - 95, "Email: nicholas.anderson@example.edu")
    
    c.setFont("Helvetica-Bold", 12)
    c.drawString(50, height - 130, "Technical Competencies & Skills:")
    c.setFont("Helvetica", 10)
    c.drawString(50, height - 145, "Python, CRISPR gene editing, Microfluidics design, Machine learning, Deep learning")
    
    c.setFont("Helvetica-Bold", 12)
    c.drawString(50, height - 180, "Research Experience:")
    c.setFont("Helvetica", 10)
    c.drawString(50, height - 195, "Assisted in engineering polymer-based microfluidic chips to capture mammalian cells.")
    
    c.save()
    print(f"Generated standards-compliant extractable PDF resume at {pdf_path}")

if __name__ == "__main__":
    create_resume_pdf()
