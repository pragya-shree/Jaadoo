// stars
const sc=document.getElementById('stars');
for(let i=0;i<110;i++){const s=document.createElement('i');s.className='star';const z=Math.random()*2+1;
s.style.cssText=`left:${Math.random()*100}%;top:${Math.random()*100}%;width:${z}px;height:${z}px;opacity:${.4+Math.random()*.6};--d:${2+Math.random()*4}s;animation-delay:-${Math.random()*5}s`;sc.appendChild(s)}
// parallax
const layers=[...document.querySelectorAll('[data-s]')];let tk=false;
addEventListener('scroll',()=>{if(tk)return;tk=true;requestAnimationFrame(()=>{const y=scrollY;layers.forEach(l=>l.style.transform=`translateY(${-y*l.dataset.s}px)`);tk=false})},{passive:true});
// alien wave
const al=document.getElementById('alien');
al.onclick=()=>{al.classList.remove('wave');void al.offsetWidth;al.classList.add('wave')};
