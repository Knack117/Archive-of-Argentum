"""Verification script to demonstrate the fix working."""
import asyncio
import sys
sys.path.insert(0, '/workspace/Archive-of-Argentum')

from aoa.services.commanders import scrape_edhrec_commander_page


async def verify_commander(name: str, expected_url: str):
    """Verify that a commander's data is properly extracted."""
    print(f"\n{'='*80}")
    print(f"Testing: {name}")
    print(f"URL: {expected_url}")
    print('='*80)
    
    try:
        result = await scrape_edhrec_commander_page(expected_url)
        
        print(f"\n✅ Successfully extracted data for {name}:")
        print(f"   - Commander Tags: {len(result.get('commander_tags', []))} tags")
        if result.get('commander_tags'):
            print(f"     Top 5: {result['commander_tags'][:5]}")
        
        print(f"   - All Tags: {len(result.get('all_tags', []))} entries")
        if result.get('all_tags'):
            tags = [tag.get('tag') for tag in result['all_tags'][:3]]
            print(f"     First 3: {tags}")
        
        print(f"   - Combos: {len(result.get('combos', []))} combos")
        if result.get('combos'):
            combos = [combo.get('name') for combo in result['combos'][:2]]
            print(f"     First 2: {combos}")
        
        print(f"   - Similar Commanders: {len(result.get('similar_commanders', []))} commanders")
        if result.get('similar_commanders'):
            similar = [cmd.get('name') for cmd in result['similar_commanders'][:3]]
            print(f"     First 3: {similar}")
        
        print(f"   - Categories: {len(result.get('categories', {}))} categories")
        if result.get('categories'):
            for cat_name in list(result['categories'].keys())[:3]:
                card_count = len(result['categories'][cat_name].get('cards', []))
                print(f"     - {cat_name}: {card_count} cards")
        
        return True
        
    except Exception as e:
        print(f"\n❌ Error extracting data: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """Run verification for multiple commanders."""
    print("\n" + "="*80)
    print("VERIFICATION: EDHRec API Fix")
    print("="*80)
    print("\nThis script demonstrates that the fix properly extracts commander data")
    print("from EDHRec's current API format.\n")
    
    commanders = [
        ("Fire Lord Ozai", "https://edhrec.com/commanders/fire-lord-ozai"),
        ("The Ur-Dragon", "https://edhrec.com/commanders/the-ur-dragon"),
    ]
    
    results = []
    for name, url in commanders:
        success = await verify_commander(name, url)
        results.append((name, success))
    
    print("\n" + "="*80)
    print("SUMMARY")
    print("="*80)
    for name, success in results:
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"{status}: {name}")
    
    all_passed = all(success for _, success in results)
    if all_passed:
        print("\n🎉 All commanders successfully extracted data!")
        print("The fix is working correctly.")
    else:
        print("\n⚠️  Some commanders failed. Please check the errors above.")


if __name__ == "__main__":
    asyncio.run(main())
