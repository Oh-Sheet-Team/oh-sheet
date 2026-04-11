import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:ohsheet_app/widgets/version_footer.dart';
import 'package:package_info_plus/package_info_plus.dart';

void main() {
  testWidgets('VersionFooter shows pubspec version when APP_VERSION unset', (tester) async {
    PackageInfo.setMockInitialValues(
      appName: 'Oh Sheet',
      packageName: 'ohsheet_app',
      version: '0.1.0',
      buildNumber: '1',
      buildSignature: '',
    );

    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(
          body: VersionFooter(),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('v0.1.0+1'), findsOneWidget);
  });
}
