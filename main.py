import re
from collections import Counter
import requests
from bs4 import BeautifulSoup
from wordcloud import WordCloud

# Free public API for remote jobs (No API key needed)
API_URL = "https://remotive.com/api/remote-jobs?category=devops&limit=100"

SKILLS_LIST = [
    # Cloud Providers
    "aws", "azure", "gcp",
    
    # Containers & Orchestration
    "docker", "kubernetes", "k8s", "helm", "podman",
    
    # Infrastructure as Code (IaC) & Configuration Management
    "terraform", "ansible", "cloudformation", "pulumi",
    
    # CI/CD & GitOps
    "ci/cd", "jenkins", "github actions", "gitlab ci", "argo cd", "flux",
    
    # Monitoring, Logging & Observability
    "prometheus", "grafana", "datadog", "elk stack", "splunk", "opentelemetry",
    
    # Operating Systems & Scripting
    "linux", "bash", "shell scripting", "python", "golang",
    
    # Security, Networking & Service Mesh
    "git", "hashicorp vault", "nginx", "istio", "sonarqube", "trivy"
]

def fetch_job_descriptions() -> list[str]:
    """Fetches latest job descriptions from the public API."""
    try:
        response = requests.get(API_URL, timeout=15)
        response.raise_for_status()
        jobs = response.json().get("jobs", [])
        
        cleaned_descriptions = []
        for job in jobs:
            raw_html = job.get("description", "")
            # Strip HTML tags
            text = BeautifulSoup(raw_html, "html.parser").get_text(separator=" ")
            cleaned_descriptions.append(text)
            
        return cleaned_descriptions
    except Exception as e:
        print(f"Error fetching jobs: {e}")
        return []

def extract_skill_frequencies(jds: list[str], skills: list[str]) -> dict[str, int]:
    skill_counts = Counter()
    sorted_skills = sorted(skills, key=len, reverse=True)
    
    for jd in jds:
        text = jd.lower()
        for skill in sorted_skills:
            pattern = rf"\b{re.escape(skill)}\b"
            if re.search(pattern, text):
                skill_counts[skill.title()] += 1
                
    return dict(skill_counts)

def generate_and_save_cloud(frequencies: dict[str, int], output_file="skills_cloud.png"):
    if not frequencies:
        print("No skills found.")
        return
        
    wc = WordCloud(
        width=1000,
        height=500,
        background_color="white",
        colormap="plasma",
        prefer_horizontal=0.9,
        min_font_size=10
    ).generate_from_frequencies(frequencies)
    
    wc.to_file(output_file)
    print(f"Successfully generated and saved {output_file}")

if __name__ == "__main__":
    jds = fetch_job_descriptions()
    print(f"Fetched {len(jds)} job postings.")
    
    freqs = extract_skill_frequencies(jds, SKILLS_LIST)
    generate_and_save_cloud(freqs)
