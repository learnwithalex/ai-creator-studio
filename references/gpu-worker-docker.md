# GPU Worker Docker Guide

- Base image: `nvidia/cuda:12.1-cudnn8-runtime-ubuntu22.04`
- Python dependencies: aiortc, onnxruntime-gpu, opencv-headless.
- Health endpoint `/health` polled by gateway every 10 seconds.
