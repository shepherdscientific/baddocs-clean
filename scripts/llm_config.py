#!/usr/bin/env python3
"""LLM configuration utility."""

import argparse

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--provider', default='anthropic')
    parser.add_argument('--model', default='claude-3-opus')
    args = parser.parse_args()
    print(f'LLM Provider: {args.provider}')
    print(f'Model: {args.model}')

if __name__ == '__main__':
    main()
