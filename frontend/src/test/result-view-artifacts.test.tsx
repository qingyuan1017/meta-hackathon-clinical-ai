import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { SubmissionPackageTree } from "@/components/result-view";
import type { Artifact } from "@/lib/types";


describe("SubmissionPackageTree", () => {
  it("shows the five package folders, their files, and empty optional folders", () => {
    const artifact = {
      id: "package-1",
      name: "sdtm-submission-package.zip",
      media_type: "application/zip",
      size_bytes: 4096,
      sha256: "a".repeat(64),
      download_url: "/api/v1/jobs/job-1/artifacts/package-1",
      package_members: [
        { path: "data", size_bytes: 0, is_directory: true },
        { path: "define", size_bytes: 0, is_directory: true },
        { path: "raw", size_bytes: 0, is_directory: true },
        { path: "spec", size_bytes: 0, is_directory: true },
        { path: "program", size_bytes: 0, is_directory: true },
        { path: "data/dm.xpt", size_bytes: 1024, is_directory: false },
        { path: "define/define.xml", size_bytes: 2048, is_directory: false },
        { path: "spec/sdtm-mapping.xlsx", size_bytes: 3072, is_directory: false },
        { path: "program/build-dm.R", size_bytes: 512, is_directory: false },
        { path: "program/build-dm.sas", size_bytes: 512, is_directory: false },
        { path: "package-manifest.json", size_bytes: 400, is_directory: false },
      ],
    } as Artifact;

    render(<SubmissionPackageTree artifact={artifact} />);

    expect(screen.getByText("data/")).toBeInTheDocument();
    expect(screen.getByText("define/")).toBeInTheDocument();
    expect(screen.getByText("raw/")).toBeInTheDocument();
    expect(screen.getByText("spec/")).toBeInTheDocument();
    expect(screen.getByText("program/")).toBeInTheDocument();
    expect(screen.getByText("dm.xpt")).toBeInTheDocument();
    expect(screen.getByText("define.xml")).toBeInTheDocument();
    expect(screen.getByText("build-dm.R")).toBeInTheDocument();
    expect(screen.getByText(/package-manifest\.json/)).toBeInTheDocument();
    expect(screen.getByText("No files available")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Download package/i })).toHaveAttribute("href", "http://localhost:8000/api/v1/jobs/job-1/artifacts/package-1");
  });
});
