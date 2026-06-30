#!/usr/bin/env python3
"""Generic language runner - supports any configured language via registry."""
import json, sys, subprocess
from pathlib import Path
from typing import Dict, Any, Optional, List

WORKSPACE_ROOT = Path("/home/scout/projects/sandbox/workspace").resolve()
COMPILE_CACHE = {}

# Core language configuration structure
LANGUAGE_CONFIG: Dict[str, Dict[str, Any]] = {
    # Compiled languages with native compilers
    'c': {
        'extensions': ['.c'],
        'compilers': {
            'default': ['gcc', '-o'],
            'cacheable': True
        },
        'compile_flags': {
            'gcc': ['-O2', '-Wall', '-Wextra']
        }
    },
    'cpp': {
        'extensions': ['.cpp', '.cc', '.cxx'],
        'compilers': {
            'default': ['g++', '-o'],
            'cacheable': True
        },
        'compile_flags': {
            'g++': ['-O2', '-Wall', '-Wextra']
        }
    },
    'go': {
        'extensions': ['.go'],
        'compilers': {
            'default': ['go', 'build', '-o'],
            'cacheable': True
        },
        'validate': [
            ('shebang', b'#!'),
            ('invalid_syntax', lambda content: 'go {' in content)
        ]
    },
    'rust': {
        'extensions': ['.rs'],
        'compilers': {
            'default': ['rustc', '-o'],
            'cacheable': True
        }
    },
    # Interpreted languages with system interpreters
    'python': {
        'extensions': ['.py'],
        'shebangs': ['python', 'python3'],
        'interpreter': 'python3'
    },
    'bash': {
        'extensions': ['.sh'],
        'shebangs': ['bash', 'sh'],
        'interpreter': 'bash'
    },
    'node': {
        'extensions': [],
        'shebangs': ['node'],
        'interpreter': 'node'
    },
    # Binary/command execution
    'binary': {
        'extensions': [],
    }
}

# Language registry manages configuration, validation, and execution
LANGUAGE_REGISTRY: Dict[str, Dict[str, Any]] = {}

def _register_languages():
    """Initialize LANGUAGE_REGISTRY from LANGUAGE_CONFIG."""
    global LANGUAGE_REGISTRY
    LANGUAGE_REGISTRY = {}
    
    for lang_name, config in LANGUAGE_CONFIG.items():
        registry_entry = {
            'lang': lang_name,
            'config': config,
            'patterns': [],
            'validations': [],
            'executable': None,
        }
        
        # Register file extensions for detection
        for ext in config.get('extensions', []):
            registry_entry['patterns'].append(('extension', ext))
        
        # Register shebang patterns for detection  
        for shebang in config.get('shebangs', []):
            registry_entry['patterns'].append(('shebang', shebang))
        
        # Setup executable (compiler or interpreter)
        if 'compilers' in config:
            compilers = config['compilers']
            registry_entry['executable'] = compilers['default'][0]
            registry_entry['cacheable'] = compilers.get('cacheable', False)
        elif 'interpreter' in config:
            registry_entry['executable'] = config['interpreter']
        
        # Register validations
        if 'validate' in config:
            for val_type, val_pattern in config['validate']:
                if val_type == 'shebang':
                    def make_shebang_checker(pattern):
                        def checker(content: bytes) -> bool:
                            return content.startswith(pattern)
                        return checker
                    registry_entry['validations'].append(make_shebang_checker(val_pattern))
                elif val_type == 'invalid_syntax':
                    registry_entry['validations'].append(val_pattern)
        
        LANGUAGE_REGISTRY[lang_name] = registry_entry

def _detect_language(path: Path) -> Optional[str]:
    """Detect language from file extension or shebang using language registry."""
    ext = path.suffix.lower()
    
    try:
        # Read shebang if present
        first_bytes = path.read_bytes()[:128]
        
        # Check shebang first for immediate identification
        if first_bytes.startswith(b'#!'):
            for lang, registry in LANGUAGE_REGISTRY.items():
                config = registry.get('config', {})
                for val_type, pattern in config.get('validations', []):
                    if val_type == 'shebang' and first_bytes.startswith(pattern):
                        return lang
        
        # Check file extension patterns
        for lang, registry in LANGUAGE_REGISTRY.items():
            config = registry.get('config', {})
            for pattern_type, pattern in registry.get('patterns', []):
                if pattern_type == 'extension' and ext == pattern:
                    return lang
        
        # Check shebang patterns if extension didn't match
        if first_bytes.startswith(b'#!'):
            for lang, registry in LANGUAGE_REGISTRY.items():
                config = registry.get('config', {})
                for shebang in config.get('shebangs', []):
                    if shebang.encode() in first_bytes:
                        return lang
        
        # Default to binary/command if no pattern matches
        return 'binary'
        
    except Exception:
        return 'binary'

def _validate_source(path: Path, lang: str) -> dict:
    """Validate source file against language-specific rules."""
    registry = LANGUAGE_REGISTRY.get(lang, {})
    if not registry:
        return None
        
    config = registry.get('config', {})
    
    # Check shebang validity (should not be present for compiled languages without shebang support)
    if 'shebangs' not in config and _has_shebang(path):
        return {
            'success': False,
            'compile_error': True,
            'language': lang,
            'output': f'{lang.upper()} source files cannot have a shebang line',
            'suggestion': f'Remove #! line from {path.name}'
        }
    
    # Run custom validations if defined
    for validation in registry.get('validations', []):
        try:
            result = validation(path)
            if result:
                return result
        except Exception:
            pass
    
    return None

def _has_shebang(path: Path) -> bool:
    """Check if file starts with shebang."""
    try:
        first = path.read_bytes()[:128]
        return first.startswith(b'#!')
    except Exception:
        return False

def _needs_compilation(lang: str) -> bool:
    """Determine if language requires compilation."""
    return 'compilers' in LANGUAGE_REGISTRY.get(lang, {}).get('config', {})

def _compile_source(path: Path, lang: str) -> dict:
    """Compile source file using language registry configuration."""
    registry = LANGUAGE_REGISTRY.get(lang, {})
    if not registry:
        return {'success': False, 'output': f'No configuration for {lang}'}
    
    config = registry.get('config', {})
    compilers = config.get('compilers', {})
    compiler_cmd = compilers.get('default', [])
    
    if not compiler_cmd:
        return {'success': False, 'output': f'No compiler specified for {lang}'}
    
    binary_path = path.with_suffix('')
    
    # Check cache
    cache_key = str(path)
    if registry.get('cacheable', False):
        cached = COMPILE_CACHE.get(cache_key)
        if cached and cached['mtime'] >= path.stat().st_mtime and cached['binary'].exists():
            return {'success': True, 'binary': str(cached['binary']), 'output': '(cached)'}
    
    try:
        # Build compilation command with flags
        base_cmd = compiler_cmd[0]
        compiler_flags = compilers.get('compile_flags', {}).get(base_cmd, [])
        cmd = compiler_flags + compiler_cmd + ['-o', str(binary_path), str(path)]
        
        timeout = 120 if lang in ('go', 'rust') else 60
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        
        if result.returncode == 0:
            if registry.get('cacheable', False):
                COMPILE_CACHE[cache_key] = {'mtime': path.stat().st_mtime, 'binary': binary_path}
            
            return {
                'success': True, 
                'binary': str(binary_path), 
                'output': result.stdout + result.stderr
            }
        
        return {'success': False, 'output': result.stdout + result.stderr}
        
    except subprocess.TimeoutExpired:
        return {'success': False, 'output': 'Compilation timed out'}
    except FileNotFoundError as e:
        return {'success': False, 'output': f'Compiler not found: {e}'}
    except Exception as e:
        return {'success': False, 'output': f'Compilation error: {e}'}

def _run_executable(path: Path, args: list, timeout: int) -> dict:
    """Execute script, binary, or interpreter."""
    try:
        # Determine if we need to use an interpreter or run binary directly
        lang = _detect_language(path)
        
        if 'shebangs' in LANGUAGE_REGISTRY.get(lang, {}).get('config', {}) or 'interpreter' in LANGUAGE_REGISTRY.get(lang, {}).get('config', {}):
            # Use interpreter for script files
            interpreter = LANGUAGE_REGISTRY[lang]['config'].get('interpreter')
            cmd = [interpreter, str(path)] + args
        else:
            # Direct binary execution
            cmd = [str(path)] + args
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        
        return {
            'success': result.returncode == 0,
            'stdout': result.stdout,
            'stderr': result.stderr,
            'exit_code': result.returncode,
        }
        
    except subprocess.TimeoutExpired:
        return {'success': False, 'error': f'Execution timed out after {timeout}s'}
    except FileNotFoundError as e:
        return {'success': False, 'error': f'Command not found: {str(e)}'}
    except Exception as e:
        return {'success': False, 'error': str(e)}

def main():
    """Generic language runner with plugin-style language support."""
    try:
        args = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        print(json.dumps({'success': False, 'error': 'Invalid JSON input'}))
        sys.exit(1)

    path = args.get('path', '')
    cmd_args = args.get('args', [])
    timeout = args.get('timeout', 30)

    if not path:
        print(json.dumps({'success': False, 'error': 'Missing path parameter'}))
        sys.exit(1)

    full_path = (WORKSPACE_ROOT / path).resolve()
    if not str(full_path).startswith(str(WORKSPACE_ROOT)):
        print(json.dumps({'success': False, 'error': 'Path outside workspace'}))
        sys.exit(1)

    # Check if path exists as file
    if not full_path.exists():
        # Check if it's a system command
        which_result = subprocess.run(['which', path], 
                                     capture_output=True, text=True)
        if which_result.returncode == 0:
            result = _run_executable(Path(which_result.stdout.strip()), cmd_args, timeout)
        else:
            result = {'success': False, 
                     'error': f'File not found: {path}', 
                     'suggestion': 'Write the source file first, then run it.'}
        print(json.dumps(result))
        return

    # Detect language and validate
    lang = _detect_language(full_path)
    
    # Validate source against language-specific rules
    validation_error = _validate_source(full_path, lang)
    if validation_error:
        print(json.dumps(validation_error))
        return

    # Handle based on language type
    if _needs_compilation(lang):
        # Compile first, then run
        compilation_result = _compile_source(full_path, lang)
        if not compilation_result['success']:
            print(json.dumps({
                'success': False,
                'compile_error': True,
                'language': lang,
                'output': compilation_result['output'],
                'suggestion': 'Fix the compilation errors above and try again.'
            }))
            return
        
        # Run the compiled binary
        run_result = _run_executable(Path(compilation_result['binary']), cmd_args, timeout)
        run_result['compile_output'] = compilation_result['output']
        print(json.dumps(run_result))
        
    else:
        # Direct execution (script or binary)
        run_result = _run_executable(full_path, cmd_args, timeout)
        print(json.dumps(run_result))

if __name__ == '__main__':
    # Initialize language registry on import
    _register_languages()
    main()
