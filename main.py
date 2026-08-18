import re
from collections import Counter
import numpy as np
import requests
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw
from wordcloud import WordCloud

API_URL = "https://remotive.com/api/remote-jobs?category=devops&limit=1000"

SKILLS_LIST = [
    # Cloud Providers
    "aws",
    "azure",
    "gcp",
    # Containers & Orchestration
    "docker",
    "kubernetes",
    "k8s",
    "helm",
    "podman",
    # IaC & Config Management
    "terraform",
    "ansible",
    "cloudformation",
    "pulumi",
    # CI/CD & GitOps
    "ci/cd",
    "jenkins",
    "github actions",
    "gitlab ci",
    "argo cd",
    "flux",
    # Monitoring & Observability
    "prometheus",
    "grafana",
    "datadog",
    "elk stack",
    "splunk",
    "opentelemetry",
    # OS & Scripting
    "linux",
    "bash",
    "shell scripting",
    "python",
    "golang",
    # Security, Networking & Mesh
    "git",
    "hashicorp vault",
    "nginx",
    "istio",
    "sonarqube",
    "trivy",
]


def fetch_job_descriptions() -> list[str]:
  try:
    response = requests.get(API_URL, timeout=15)
    response.raise_for_status()
    jobs = response.json().get("jobs", [])
    return [
        BeautifulSoup(j.get("description", ""), "html.parser").get_text(
            separator=" "
        )
        for j in jobs
    ]
  except Exception as e:
    print(f"Error fetching jobs: {e}")
    return []


def extract_skill_frequencies(
    jds: list[str], skills: list[str]
) -> dict[str, float]:
  skill_counts = Counter()
  sorted_skills = sorted(skills, key=len, reverse=True)

  # Acronym normalization lookup
  display_names = {
      "aws": "AWS",
      "gcp": "GCP",
      "ci/cd": "CI/CD",
      "k8s": "K8s",
      "iac": "IaC",
  }

  for jd in jds:
    text = jd.lower()
    for skill in sorted_skills:
      pattern = rf"\b{re.escape(skill)}\b"
      if re.search(pattern, text):
        clean_name = display_names.get(skill.lower(), skill.title())
        skill_counts[clean_name] += 1

  if not skill_counts:
    return {}

  # Contrast Boost: Apply power scaling so top skills are visibly dominant
  max_count = max(skill_counts.values())
  scaled_freqs = {
      skill: (count / max_count) ** 1.35 for skill, count in skill_counts.items()
  }

  return scaled_freqs


def custom_color_func(
    word, font_size, position, orientation, random_state=None, **kwargs
):
  """Custom dynamic color palette: Electric Cyan -> Violet -> Coral based on size."""
  if font_size > 140:
    return "#38bdf8"  # Neon Sky Blue (Dominant Skills)
  elif font_size > 90:
    return "#818cf8"  # Electric Indigo
  elif font_size > 50:
    return "#c084fc"  # Soft Violet
  elif font_size > 30:
    return "#f472b6"  # Pink Coral
  else:
    return "#64748b"  # Slate Muted Gray (Fillers)


def create_rounded_mask(width: int, height: int, radius: int = 80) -> np.ndarray:
  """Creates a smooth rounded rectangle mask to give clean container edges."""
  img = Image.new("L", (width, height), 255)
  draw = ImageDraw.Draw(img)
  draw.rounded_rectangle([(0, 0), (width, height)], radius=radius, fill=0)
  return np.array(img)


def generate_and_save_cloud(
    frequencies: dict[str, float], output_file="skills_cloud_pro.png"
):
  if not frequencies:
    print("No skills found.")
    return

  canvas_width = 2400
  canvas_height = 1350
  mask = create_rounded_mask(canvas_width, canvas_height, radius=120)

  wc = WordCloud(
      width=canvas_width,
      height=canvas_height,
      scale=2,  # Ultra-crisp rendering
      background_color="#090d16",  # Deep Midnight / Obsidian Dark
      mask=mask,
      color_func=custom_color_func,
      prefer_horizontal=0.90,  # 90% horizontal for high readability
      min_font_size=16,
      max_font_size=230,
      margin=8,  # Breathing room between words
      relative_scaling=0.45,  # Balanced distribution between size and frequency
      collocations=False,
      # font_path="path/to/Inter-Bold.ttf"  # Optional: path to custom TTF font
  ).generate_from_frequencies(frequencies)

  wc.to_file(output_file)
  print(f"High-fidelity word cloud saved to {output_file}")


if __name__ == "__main__":
  jds = fetch_job_descriptions()
  print(f"Fetched {len(jds)} job postings.")

  freqs = extract_skill_frequencies(jds, SKILLS_LIST)
  generate_and_save_cloud(freqs)
