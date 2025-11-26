"""Validate OpenAPI schemas for CustomGPT compliance."""
import json
import re
from pathlib import Path

def validate_schema_file(json_file: Path) -> dict:
    """Validate an OpenAPI schema file for common issues."""
    results = {
        'file': str(json_file),
        'valid': True,
        'issues': [],
        'warnings': []
    }
    
    try:
        with open(json_file, 'r') as f:
            schema = json.load(f)
        
        paths = schema.get('paths', {})
        operation_count = sum(len(methods) for methods in paths.values())
        
        # Check operation count
        if operation_count > 30:
            results['issues'].append(f"Too many operations: {operation_count}/30")
            results['valid'] = False
        else:
            results['warnings'].append(f"Operation count: {operation_count}/30")
        
        # Check for validation issues
        mld_endpoint = paths.get('/api/v1/cards/mass-land-destruction')
        if mld_endpoint and mld_endpoint.get('get'):
            desc = mld_endpoint['get'].get('description', '')
            if len(desc) > 300:
                results['issues'].append(f"Mass Land Destruction description too long: {len(desc)}/300 chars")
                results['valid'] = False
        
        # Check schema definitions for status, root, health
        problematic_endpoints = {'/api/v1/status', '/', '/health'}
        for endpoint in problematic_endpoints:
            endpoint_data = paths.get(endpoint)
            if endpoint_data:
                for method_data in endpoint_data.values():
                    responses = method_data.get('responses', {})
                    if '200' in responses:
                        content = responses['200'].get('content', {})
                        if 'application/json' in content:
                            schema_def = content['application/json'].get('schema', {})
                            if (schema_def.get('additionalProperties') is True and 
                                'properties' not in schema_def):
                                results['issues'].append(f"Missing schema properties for {endpoint}")
                                results['valid'] = False
        
        # Check for required OpenAPI components
        if 'openapi' not in schema:
            results['issues'].append("Missing OpenAPI version")
            results['valid'] = False
            
        if 'info' not in schema:
            results['issues'].append("Missing info section")
            results['valid'] = False
            
        if 'paths' not in schema:
            results['issues'].append("Missing paths section")
            results['valid'] = False
        
    except json.JSONDecodeError as e:
        results['issues'].append(f"Invalid JSON: {e}")
        results['valid'] = False
    except Exception as e:
        results['issues'].append(f"Error reading file: {e}")
        results['valid'] = False
    
    return results

def main():
    """Validate all generated OpenAPI schema files."""
    schema_files = [
        'system_cards.json',
        'commanders_combos.json', 
        'themes_deck_validation.json',
        'popular_decks_cedh.json'
    ]
    
    print("🔍 OpenAPI Schema Validation Report")
    print("=" * 60)
    
    all_valid = True
    total_operations = 0
    
    for schema_file in schema_files:
        schema_path = Path(schema_file)
        if schema_path.exists():
            results = validate_schema_file(schema_path)
            
            status = "✅ PASS" if results['valid'] else "❌ FAIL"
            print(f"\n{status} {schema_file}")
            
            if results['warnings']:
                for warning in results['warnings']:
                    print(f"   ⚠️  {warning}")
            
            if results['issues']:
                for issue in results['issues']:
                    print(f"   ❌ {issue}")
                all_valid = False
            
            # Count operations
            try:
                with open(schema_path, 'r') as f:
                    schema = json.load(f)
                    ops = sum(len(methods) for methods in schema.get('paths', {}).values())
                    total_operations += ops
                    print(f"   📊 Operations: {ops}")
            except:
                pass
        else:
            print(f"❌ {schema_file} - FILE NOT FOUND")
            all_valid = False
    
    print(f"\n{'=' * 60}")
    print(f"📊 Total Operations: {total_operations}")
    print(f"📊 Files Validated: {len([f for f in schema_files if Path(f).exists()])}")
    
    if all_valid:
        print(f"\n✅ All schemas are valid for CustomGPT!")
    else:
        print(f"\n❌ Some schemas have validation issues!")
    
    return all_valid

if __name__ == "__main__":
    main()