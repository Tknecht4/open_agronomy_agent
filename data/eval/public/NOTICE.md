# CROP benchmark attribution and change notice

The CROP-derived evaluation file in this directory is distributed under the
[Creative Commons Attribution-NonCommercial 4.0 International
license](https://creativecommons.org/licenses/by-nc/4.0/).

Source: `AI4Agr/CROP-benchmark`, test split, revision
`1b569e9fec64fc7ad868e6e383fa9846b00ce69d`, `test/benchmark.json`.

Authors: Hang Zhang, Jiawei Sun, Renqi Chen, Wei Liu, Zhonghang Yuan, Xinzhe
Zheng, Zhefan Wang, Zhiyuan Yang, Hang Yan, Hansen Zhong, Xiqing Wang, Wanli
Ouyang, Fan Yang, and Nanqing Dong.

Paper: “Empowering and Assessing the Utility of Large Language Models in Crop
Science,” NeurIPS 2024 Datasets and Benchmarks Track, DOI
10.52202/079017-1669.

Changes made by this project:

- retained English-eligible rows only;
- excluded four source rows exposed during the retired v1 development smoke
  and all source rows in the retired 216-question v2 profile;
- selected a deterministic 180-question v3 profile with 60 rows per published
  difficulty level and correct-option word-length-rank counts of 44/45/45/46;
- permuted answer options deterministically to balance correct answer position;
- converted answer labels to Roman numerals; and
- added local provenance, scoring, and contamination metadata.

The source question and option wording was not rewritten. No endorsement by the
original authors or institutions is implied. This notice and the adjacent source
manifest must accompany redistribution of the derived evaluation file.
