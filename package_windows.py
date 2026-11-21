"""Create a portable Windows archive from the PyInstaller build."""
from importlib.metadata import distributions
from pathlib import Path
import shutil
import sys

from analisi._version import VERSION


def main():
    root = Path(__file__).resolve().parent
    bundle = root / "dist" / "Trama"
    if not (bundle / "Trama.exe").is_file():
        raise SystemExit("Build Trama.exe first.")
    for label, flag in (("Tk", "--tk"), ("Qt", "--qt")):
        launcher = bundle / f"Trama - {label}.cmd"
        launcher.write_bytes(f'@echo off\r\nstart "" /D "%~dp0." "%~dp0Trama.exe" {flag}\r\n'.encode("ascii"))
    shutil.copy2(root / "README.md", bundle / "README.md")
    shutil.copy2(root / "LICENSE", bundle / "LICENSE.txt")
    shutil.copy2(root / "LICENSE", bundle / "LICENSE")
    for name in ("README.en.md", "THIRD_PARTY_NOTICES.md"):
        shutil.copy2(root / name, bundle / name)
    for name in ("features.md", "getting-started.md", "compatibility.md", "development.md", "legal.md",
                 "competing-risks.md", "kmeans-algorithms.md", "independent-roc-curves.md", "ancova-090.md",
                 "grouped-distributions.md", "qt-migration.md", "qt-canvas-095.md", "qt-gallery.md",
                 "project-tabs-qt.md", "qt-batch-export.md", "qt-graph-style-presets.md", "qt-report.md", "worksheet-join.md", "qt-recovery.md", "qt-analysis-templates.md",
                 "qt-excel-workbook.md", "cluster-silhouette-092.md", "paired-proportions.md", "power-from-summary.md",
                 "tolerance-intervals-093.md", "weibull-aft.md", "ordinal-logit.md", "restricted-mean-survival.md", "cohen-kappa.md", "mean-permutation-test.md", "xy-mixed-series.md",
                 "release-098.md", "release-097.md", "release-094.md",
                 "release-093.md", "validation-093.md",
                 "release-092.md", "validation-092.md", "release-091.md", "validation-091.md",
                 "pca-regression-087.md", "release-090.md", "validation-090.md",
                 "release-089.md", "validation-089.md", "release-088.md", "validation-088.md",
                 "release-087.md", "validation-087.md",
                 "pca-reports.md", "release-086.md", "validation-086.md",
                 "release-085.md", "validation-085.md",
                 "formula-windows.md", "distribution-formulas.md", "confidence-ellipses.md",
                 "anova-terms-083.md", "anova-ss-types.md", "anova-planned-contrasts.md", "rm-anova-sphericity.md", "kmeans-stability.md",
                 "curve-pipeline.md", "deming-multiseries-093.md", "exact-binomial.md", "repeated-measures-correlation.md",
                 "meta-analysis.md", "cox-exact-ties.md", "cox-fit-diagnostics.md", "nb2-regression.md",
                 "logistic-validation.md", "bland-altman-repeated.md", "icc.md", "precision-recall.md", "reshape-long-wide.md",
                 "release-084.md", "validation-084.md", "hierarchical-style-081.md", "release-083.md", "validation-083.md",
                 "conditional-equations-081.md", "graph-legends.md", "release-082.md", "validation-082.md",
                 "release-081.md", "validation-081.md", "experiment-families.md", "variance-ratio-079.md",
                 "release-080.md", "validation-080.md", "hierarchical-import.md", "leaf-ordering.md",
                 "release-079.md", "validation-079.md", "analysis-chains.md",
                 "release-078.md", "validation-078.md", "fdr-control.md", "axis-guides.md", "axis-breaks.md",
                 "release-077.md", "validation-077.md", "release-076.md", "validation-076.md", "startup-screen.md", "release-075.md", "validation-075.md", "release-074.md", "validation-074.md", "release-history.md", "release-071.md", "release-072.md", "release-073.md", "validation-073.md", "interface-themes.md", "summary-unequal-anova.md", "validation-tost-086.md", "linear-point-estimates.md",
                 "nonlinear-parameter-intervals.md", "custom-parameter-profiles.md", "global-custom-parameter-profiles.md", "global-custom-070.md", "lognormal-tests-070.md", "equivalence-tost-071.md", "pca-selection-070.md",
                 "weighted-multiple-regression-070.md", "anova-diagnostics-070.md", "variance-assumptions-070.md",
                 "heatmap-colors-072.md", "robust-curve-073.md", "reference-normalization.md",
                 "nonlinear-inverse-intervals-073.md", "heatmap-layout.md", "correlation-details.md", "spearman-exact-extended.md", "lognormality.md", "summary-anova.md", "qq-panels.md", "lognormal-anova.md", "summary-ttest.md"):
        (bundle / "docs").mkdir(exist_ok=True)
        if (root / "docs" / name).is_file():
            shutil.copy2(root / "docs" / name, bundle / "docs" / name)
    shutil.copytree(root / "assets" / "brand", bundle / "assets" / "brand", dirs_exist_ok=True)
    for name in ("trama.svg", "trama.png", "trama.ico"):
        shutil.copy2(root / "assets" / name, bundle / "assets" / name)
    for name in ("coverage.md", "mixed-global.md", "candidate-062.md", "validation-062.json", "drawing-063.md", "drawing-064.md", "drawing-065.md", "editor-066-status.md", "context-067.md", "drawing-clipboard-068.md", "pattern-color-069.md", "arrangement-070.md", "movement-071.md", "global-custom-070.md"):
        source = root / "docs" / name
        if source.is_file():
            (bundle / "docs").mkdir(exist_ok=True)
            shutil.copy2(source, bundle / "docs" / name)
    shutil.rmtree(bundle / "docs" / "media", ignore_errors=True)
    # Product media only. Raw extracted resources and historical imported
    # drawings are research evidence, not approved redistribution assets.
    for folder in ("workflows-093", "kmeans-stability-096", "hartigan-wong-092", "pca-import-091", "pca-regression-090", "pca-regression-087", "pca-overlays-089", "categorical-scatter-088", "pca-reports-087", "anova-ellipses-085", "anova-terms-083", "anova-ss-types", "rm-sphericity", "hierarchical-style-084", "conditional-hierarchical", "graph-legends", "experiment-families", "variance-ratio-079", "hierarchical-import", "analysis-chains", "fdr-axis", "startup", "custom-parameter-profiles", "global-custom-parameter-profiles", "nonlinear-parameter-intervals", "homepage", "interface-themes", "summary-unequal-anova", "linear-point-estimates", "pca-selection-070",
                   "anova-diagnostics-070", "variance-assumptions-070", "reference-normalization",
                   "logistic-validation-096", "cox-fit-diagnostics"):
        source = root / "docs" / "media" / folder
        if source.is_dir():
            shutil.copytree(source, bundle / "docs" / "media" / folder, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns("*.txt", "*.log"))
    robust_image = root / "docs" / "media" / "robust-curve-073.png"
    if robust_image.is_file():
        (bundle / "docs" / "media").mkdir(exist_ok=True)
        shutil.copy2(robust_image, bundle / "docs" / "media" / robust_image.name)
    # Remove research material that could remain in a reused build directory.
    for name in ("Laboratorio.alab", "rm-two-way-sphericity.alab", "Curve-pipeline.alab", "Assi-interrotti.alab",
                 "Stabilita-KMeans.alab", "Validazione-Logistica.alab", "Bland-Altman-ripetute.alab",
                 "rimodella-visite.alab", "ICC-valutatori.alab", "Precisione-Richiamo.alab"):
        example = root / "docs" / "examples" / name
        if example.is_file():
            (bundle / "docs" / "examples").mkdir(exist_ok=True)
            shutil.copy2(example, bundle / "docs" / "examples" / example.name)
    examples = bundle / "docs" / "examples"
    examples.mkdir(parents=True, exist_ok=True)
    shutil.copy2(root / "tests" / "data" / "tolerance_093" / "measurements.csv", examples / "tolerance-intervals.csv")
    shutil.copy2(root / "tests" / "data" / "weibull_aft" / "follow-up.csv", examples / "weibull-follow-up.csv")
    shutil.copy2(root / "tests" / "data" / "ordinal_logit" / "stages.csv", examples / "ordinal-stages.csv")
    shutil.copy2(root / "tests" / "data" / "rmst" / "fixtures" / "cohorts.csv", examples / "rmst-cohorts.csv")
    shutil.copy2(root / "tests" / "data" / "cohen_kappa" / "ratings.csv", examples / "cohen-kappa-ratings.csv")
    for design in ("independent", "paired"):
        shutil.copy2(root / "tests" / "data" / "mean_permutation" / f"{design}.csv",
                     examples / f"permutation-{design}.csv")
    notices = bundle / "Third-party licenses"
    for dist in distributions():
        for item in dist.files or ():
            if "licenses" in item.parts[:-1]:
                relative = Path(*item.parts[item.parts.index("licenses") + 1:])
            elif any(part.lower().startswith(("license", "copying", "notice")) for part in item.parts[-2:]):
                relative = Path(item.name)
            else:
                continue
            source = dist.locate_file(item)
            if source.is_file():
                target = notices / dist.metadata["Name"] / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists() and target.read_bytes() != source.read_bytes():
                    target = target.with_name(f"{item.parent.name}-{item.name}")
                shutil.copy2(source, target)
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if python_license.is_file():
        (notices / "Python").mkdir(parents=True, exist_ok=True)
        shutil.copy2(python_license, notices / "Python" / python_license.name)
    path = shutil.make_archive(str(bundle.parent / f"Trama-{VERSION}-Windows-x64"),
                               "zip", root_dir=bundle.parent, base_dir=bundle.name)
    print(path)


if __name__ == "__main__":
    main()
