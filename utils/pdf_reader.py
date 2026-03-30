import fitz  # PyMuPDF
import os

def extract_text_from_pdf(pdf_path):
    """
    Extracts text from a PDF file using PyMuPDF.
    """
    if not os.path.exists(pdf_path):
        return f"Error: File {pdf_path} not found."
    
    try:
        doc = fitz.open(pdf_path)
        text = ""
        for page in doc:
            blocks = page.get_text("blocks")
            # Filter and convert to list to avoid weirdness
            clean_blocks = []
            for b in blocks:
                if b[4].strip():
                    clean_blocks.append(list(b))
            
            # Sort by top coordinate
            clean_blocks.sort(key=lambda b: b[1])
            
            lines = []
            if clean_blocks:
                current_line_blocks = [clean_blocks[0]]
                for i in range(1, len(clean_blocks)):
                    prev_b = clean_blocks[i-1]
                    curr_b = clean_blocks[i]
                    
                    # If vertical start is within 5px, it's the same line
                    if abs(curr_b[1] - prev_b[1]) < 5:
                        current_line_blocks.append(curr_b)
                    else:
                        # Sort current line left to right
                        current_line_blocks.sort(key=lambda b: b[0])
                        # Use '|' as a clear column separator if there's a significant gap
                        line_parts = []
                        for k in range(len(current_line_blocks)):
                            part = current_line_blocks[k][4].strip()
                            if k > 0:
                                gap = current_line_blocks[k][0] - current_line_blocks[k-1][2]
                                if gap > 20: # Significant horizontal gap
                                    line_parts.append("|")
                            line_parts.append(part)
                        lines.append(" ".join(line_parts))
                        current_line_blocks = [curr_b]
                
                # Append last line
                current_line_blocks.sort(key=lambda b: b[0])
                line_parts = []
                for k in range(len(current_line_blocks)):
                    part = current_line_blocks[k][4].strip()
                    if k > 0:
                        gap = current_line_blocks[k][0] - current_line_blocks[k-1][2]
                        if gap > 20:
                            line_parts.append("|")
                    line_parts.append(part)
                lines.append(" ".join(line_parts))
            
            text += "\n".join(lines) + "\n"
            
            if len(text) > 15000:
                text = text[:15000]
                break
        
        doc.close()
        return text.strip()
    except Exception as e:
        return f"Error extracting text: {str(e)}"

