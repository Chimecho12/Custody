// 화면 전체를 그림으로 남기는 공용 도우미. UI 점검 스크립트들이 같은 규칙으로 찍는다.
const viewHeight = 920;
const shotMaxHeight = 4000;
// 셸은 창이 아니라 main 을 스크롤한다(app.css 의 `body{overflow:hidden}`). 그래서 fullPage 만으로는
// 뷰포트 아래가 그림에 담기지 않는다. 넘치는 만큼 뷰포트를 늘려 찍고 원래 높이로 되돌린다.
async function shoot(page, width, file) {
  let height = viewHeight;
  let clipped = false;
  for (let pass = 0; pass < 2; pass += 1) {
    const overflow = await page.evaluate(() => {
      const main = document.querySelector('main');
      return main ? Math.ceil(main.scrollHeight - main.clientHeight) : 0;
    });
    if (overflow <= 0) break;
    clipped = height + overflow > shotMaxHeight;
    height = clipped ? shotMaxHeight : height + overflow;
    await page.setViewportSize({width, height});
    if (clipped) break;
  }
  await page.screenshot({path:file, fullPage:true});
  if (height !== viewHeight) await page.setViewportSize({width, height:viewHeight});
  // 상한에 걸려 잘린 그림은 결과에 적어 둔다. 조용히 범위가 줄면 회귀를 놓친다.
  return {height, clipped};
}

module.exports = {viewHeight, shotMaxHeight, shoot};
